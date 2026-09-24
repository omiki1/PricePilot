<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'
import {
  addFavorite,
  fetchFavorites,
  fetchHealth,
  openChat,
  removeFavorite,
} from './api.js'
import { renderMarkdown } from './markdown.js'

const userId = ref('u001')
const sessionId = ref('s001')
const input = ref('')
const showSettings = ref(false)

// ---- 收藏 ----
// showFavorites 这个名字来自 style.css 的注释：收藏栏只在它为真时渲染，不占位
const showFavorites = ref(false)
const favorites = ref([])
const favError = ref('')
const favBusy = ref('') // 正在操作的商品 ID：期间禁用按钮，防连点

const messages = ref([])          // {role, text, products, streaming, error, showAll}
const sending = ref(false)
const health = ref(null)
const scrollRef = ref(null)
const textareaRef = ref(null)
const failedImages = reactive(new Set())

const samples = [
]

// 后端目前会把全部候选一起推回来，这里把"有证据的"和"排前面的"当成推荐位
function pickRecommended(products) {
  if (!products || !products.length) return []
  const withEvidence = products.filter((p) => (p.evidence || []).length > 0)
  if (withEvidence.length) return withEvidence.slice(0, 3)
  return products.slice(0, 3)
}

function otherProducts(products) {
  const recommended = new Set(pickRecommended(products).map((p) => p.product_id))
  return (products || []).filter((p) => !recommended.has(p.product_id))
}

async function scrollToBottom(force = false) {
  await nextTick()
  const el = scrollRef.value
  if (!el) return
  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160
  if (force || nearBottom) el.scrollTop = el.scrollHeight
}

function autoGrow() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 168)}px`
}

function onSend() {
  const question = input.value.trim()
  if (!question || sending.value) return

  sending.value = true
  messages.value.push({ role: 'user', text: question })
  const reply = reactive({
    role: 'assistant', text: '', products: [], streaming: true, error: '', showAll: false,
  })
  messages.value.push(reply)
  input.value = ''
  nextTick(autoGrow)
  scrollToBottom(true)

  openChat({
    question,
    userId: userId.value,
    sessionId: sessionId.value,
    onText: (chunk) => {
      reply.text += chunk
      scrollToBottom()
    },
    onProducts: (products) => {
      reply.products = products
      scrollToBottom()
    },
    onError: (detail) => {
      reply.error = detail
    },
    onDone: () => {
      reply.streaming = false
      sending.value = false
      scrollToBottom()
    },
  })
}

function onKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    onSend()
  }
}

function useSample(text) {
  input.value = text
  nextTick(() => {
    autoGrow()
    textareaRef.value?.focus()
  })
}

function priceText(product) {
  // ── [B 修改 2026-09-24] 优先用后端给的人民币展示串 ──
  // 后端现在会下发 price_text，形如「USD 56.98 / 人民币 ≈ ¥383.06」，
  // 汇率口径由后端统一掌握（见 app/ai/tool/currency.py），前端不再自己换算。
  // 没有该字段时（旧数据 / 其他数据源）退回下面按 min/max 拼装的老逻辑。
  if (product.price_text) return product.price_text
  // 后端现在把价格拆成区间：min_price / max_price（流式商品帧与最终商品列表同名）。
  // 旧字段 price 仅在单值场景下兜底，保证历史数据也能渲染。
  const low = product.min_price ?? product.price
  const high = product.max_price ?? product.price
  if (low === null || low === undefined) {
    if (high === null || high === undefined) return '价格待确认'
    return `${product.currency || ''} ${high}`.trim()
  }
  if (high === null || high === undefined || high === low) {
    return `${product.currency || ''} ${low}`.trim()
  }
  return `${product.currency || ''} ${low}~${high}`.trim()
}

function scoreText(product) {
  return product.score === null || product.score === undefined ? '' : `加权 ${product.score}`
}

// 只有走完 recommend 节点（排过序）的商品才断言"样本不足"；
// 检索中途推送的卡片还没排序，缺评分不代表样本不足，那时不显示这句。
function isRanked(product) {
  return product.score !== undefined || product.rating_count !== undefined
}

function ratingText(product) {
  if (typeof product.rating === 'number') {
    const count = product.rating_count ? `（${product.rating_count}）` : ''
    return `★ ${product.rating}${count}`
  }
  return isRanked(product) ? '评价样本不足' : ''
}

function imageFailed(product) {
  return failedImages.has(product.product_id)
}

function markImageFailed(product) {
  failedImages.add(product.product_id)
}

// ---------- 收藏 ----------

/** 商品卡上的按钮要知道这一条收藏了没有。收藏夹最多 100 条，直接找就够快。 */
function isFavorited(productId) {
  return favorites.value.some((item) => item.product_id === productId)
}

/**
 * 商品 → 收藏接口要的载荷。
 *
 * 后端 FavoriteProduct 只认这几个字段（model_config extra="ignore"，多余的自动丢），
 * 但 price 必须是数字：后端把价格拆成了 min_price / max_price 区间，
 * 取不到时退回旧字段 price，都没有就传 null（后端允许）。
 */
function favoritePayload(product) {
  let price = null
  if (typeof product.min_price === 'number') price = product.min_price
  else if (typeof product.price === 'number') price = product.price
  return {
    product_id: product.product_id,
    title: product.title || '',
    image_url: product.image_url || null,
    product_url: product.product_url || product.url || null,
    price,
  }
}

async function loadFavorites() {
  favError.value = ''
  try {
    const data = await fetchFavorites({ userId: userId.value })
    favorites.value = data.favorites || []
  } catch (error) {
    favError.value = error.message || '收藏夹加载失败'
  }
}

/** 卡片按钮：没收藏就收藏，已收藏就取消。两个方向都靠 isFavorited 判断。 */
async function toggleFavorite(product) {
  const id = product.product_id
  if (!id || favBusy.value) return
  favBusy.value = id
  favError.value = ''
  try {
    if (isFavorited(id)) {
      await removeFavorite({ userId: userId.value, productId: id })
    } else {
      await addFavorite({ userId: userId.value, product: favoritePayload(product) })
    }
    await loadFavorites()
  } catch (error) {
    favError.value = error.message || '操作失败'
  } finally {
    favBusy.value = ''
  }
}

function removeFavoriteItem(item) {
  return toggleFavorite({ product_id: item.product_id })
}

function toggleFavorites() {
  if (showFavorites.value) {
    showFavorites.value = false
    return
  }
  showFavorites.value = true
  loadFavorites()
}

onMounted(async () => {
  try {
    health.value = await fetchHealth()
  } catch (exception) {
    health.value = { status: 'unreachable', error: exception.message }
  }
  // 进页面就把收藏夹拉下来：卡片上的按钮靠它决定显示"收藏"还是"已收藏"
  loadFavorites()
  textareaRef.value?.focus()
})
</script>

<template>
  <div class="page">
    <header class="topbar">
      <div class="brand">
        <h1>PricePilot</h1>
        <span class="tagline">购物助手 · 意图识别 → 商品检索 → 推荐</span>
      </div>
      <div class="topbar-right">
        <span class="badge" :class="health && health.status === 'ok' ? 'badge-ok' : 'badge-bad'">
          后端{{ health ? (health.status === 'ok' ? '正常' : health.status) : '检测中' }}
        </span>
        <button class="settings-toggle" type="button" @click="toggleFavorites">
          {{ showFavorites ? '收起收藏夹' : '收藏夹' }}{{ favorites.length ? ` ${favorites.length}` : '' }}
        </button>
        <button class="settings-toggle" type="button" @click="showSettings = !showSettings">
          {{ showSettings ? '收起设置' : '会话设置' }}
        </button>
      </div>
    </header>

    <div v-if="showSettings" class="settings">
      <label class="field">
        <span>用户 ID</span>
        <input v-model="userId" type="text" />
      </label>
      <label class="field">
        <span>会话 ID（同一 ID 共享图状态）</span>
        <input v-model="sessionId" type="text" />
      </label>
    </div>

    <!-- 聊天区与收藏栏并排：.main 是 flex 容器，收藏栏在左（CSS 里是 border-right） -->
    <div class="main">
      <aside v-if="showFavorites" class="fav-side">
        <div class="fav-side-head">
          <h3>收藏夹{{ favorites.length ? `（${favorites.length}）` : '' }}</h3>
          <button class="fav-side-close" type="button" title="收起" @click="showFavorites = false">×</button>
        </div>

        <p v-if="favError" class="fav-side-error">{{ favError }}</p>

        <div v-if="!favorites.length" class="fav-side-hint">
          <p>还没有收藏。在商品卡上点「收藏」，这里就会出现。</p>
        </div>

        <div v-else class="fav-side-list">
          <div v-for="item in favorites" :key="item.id" class="fav-side-item">
            <div class="fav-side-thumb">
              <img
                v-if="item.image_url && !failedImages.has(item.product_id)"
                :src="item.image_url"
                :alt="item.title"
                loading="lazy"
                @error="failedImages.add(item.product_id)"
              />
              <span v-else>无图</span>
            </div>

            <div class="fav-side-info">
              <div class="fav-side-title" :title="item.title">{{ item.title || '未命名商品' }}</div>
              <div class="fav-side-line">
                <span class="fav-side-price">{{ item.price || '价格未知' }}</span>
                <span class="fav-side-time">{{ (item.time || '').slice(0, 10) }}</span>
              </div>
            </div>

            <div class="fav-side-actions">
              <a v-if="item.product_url" :href="item.product_url" target="_blank" rel="noopener">商品页</a>
              <button
                class="fav-side-remove"
                type="button"
                :disabled="favBusy === item.product_id"
                @click="removeFavoriteItem(item)"
              >
                移除
              </button>
            </div>
          </div>
        </div>
      </aside>

      <div ref="scrollRef" class="scroll">
      <div class="thread">
        <div v-if="!messages.length" class="empty">
          <h2>想买点什么？</h2>
          <p>说清商品和预算，我来帮你找。</p>
        </div>

        <div v-for="(message, index) in messages" :key="index" class="msg" :class="message.role">
          <div class="avatar">{{ message.role === 'user' ? '我' : 'PP' }}</div>

          <div class="body">
            <div class="who">{{ message.role === 'user' ? '你' : 'PricePilot' }}</div>

            <div v-if="message.role === 'assistant' && !message.text && message.streaming" class="thinking">
              <span class="dots"><span></span><span></span><span></span></span>
              正在思考…
            </div>

            <!-- 助手消息：走 Markdown 渲染。
                 .md 会关掉 .text 的 white-space: pre-wrap —— 否则 v-html 生成的
                 HTML 里那些标签之间的换行会被当成可见空行，排版全乱。 -->
            <div v-if="message.text && message.role === 'assistant'" class="text md">
              <div class="md-body" v-html="renderMarkdown(message.text)"></div>
              <span v-if="message.streaming" class="caret"></span>
            </div>

            <!-- 用户消息：原样纯文本，不解析 Markdown（用户打的 "**" 就该显示 "**"） -->
            <div v-else-if="message.text" class="text">{{ message.text }}</div>

            <!-- 推荐商品：带序号，和上面的文字一一对应 -->
            <section v-if="pickRecommended(message.products).length" class="picks">
              <h4 class="section-title">
                推荐商品
                <span class="section-note">与上方「商品 1 / 2 / 3」顺序一致</span>
              </h4>

              <article
                v-for="(product, pickIndex) in pickRecommended(message.products)"
                :key="product.product_id"
                class="pick"
              >
                <div class="pick-no">{{ pickIndex + 1 }}</div>

                <div class="pick-thumb">
                  <img
                    v-if="product.image_url && !imageFailed(product)"
                    :src="product.image_url"
                    :alt="product.title"
                    loading="lazy"
                    @error="markImageFailed(product)"
                  />
                  <span v-else>暂无图片</span>
                </div>

                <div class="pick-info">
                  <div class="pick-head">
                    <h3 class="pick-title" :title="product.title">{{ product.title }}</h3>
                    <button
                      class="fav-btn"
                      :class="{ 'fav-btn-on': isFavorited(product.product_id) }"
                      type="button"
                      :disabled="favBusy === product.product_id"
                      @click="toggleFavorite(product)"
                    >
                      {{ isFavorited(product.product_id) ? '已收藏' : '收藏' }}
                    </button>
                  </div>

                  <p class="pick-line">
                    <strong class="pick-price">{{ priceText(product) }}</strong>
                    <span v-if="scoreText(product)" class="pick-score">{{ scoreText(product) }}</span>
                    <span
                      v-if="ratingText(product)"
                      class="pick-rating"
                      :class="{ 'pick-norating': typeof product.rating !== 'number' }"
                    >
                      {{ ratingText(product) }}
                    </span>
                    <span v-if="product.available === true" class="pick-stock">有货</span>
                  </p>

                  <p class="pick-meta">{{ [product.seller, product.platform].filter(Boolean).join(' · ') }}</p>

                  <!-- 证据列表 -->
                  <details v-if="(product.evidence || []).length" class="evidence">
                    <summary>第三方证据 {{ product.evidence.length }} 条</summary>
                    <ul>
                      <li v-for="item in product.evidence" :key="item.url || item.title">
                        <a v-if="item.url" :href="item.url" target="_blank" rel="noopener">{{ item.title || '来源' }}</a>
                        <span v-else>{{ item.title || '来源' }}</span>
                        <em v-if="item.site"> · {{ item.site }}</em>
                        <span v-if="item.date" class="ev-date"> {{ item.date }}</span>
                        <p class="ev-snippet">{{ item.snippet }}</p>
                      </li>
                    </ul>
                  </details>
                  <p v-else class="pick-note">未检索到第三方证据，此条结论仅依据评分与规格。</p>

                  <a v-if="product.url" class="pick-link" :href="product.url" target="_blank" rel="noopener">查看商品页 →</a>
                </div>
              </article>
            </section>

            <!-- 其余候选：默认折叠，避免几十张卡把页面撑爆 -->
            <section v-if="otherProducts(message.products).length" class="others">
              <button class="others-toggle" type="button" @click="message.showAll = !message.showAll">
                {{ message.showAll ? '收起' : '展开' }}其他 {{ otherProducts(message.products).length }} 个候选
              </button>

              <div v-if="message.showAll" class="grid">
                <article v-for="product in otherProducts(message.products)" :key="product.product_id" class="card">
                  <img
                    v-if="product.image_url && !imageFailed(product)"
                    class="thumb"
                    :src="product.image_url"
                    :alt="product.title"
                    loading="lazy"
                    @error="markImageFailed(product)"
                  />
                  <div v-else class="thumb-empty">暂无图片</div>
                  <div class="card-body">
                    <h3 class="card-title" :title="product.title">{{ product.title }}</h3>
                    <span class="card-price">{{ priceText(product) }}</span>
                    <p class="card-meta">{{ [product.seller, product.platform].filter(Boolean).join(' · ') || '—' }}</p>
                    <p class="card-tags">
                      <span v-if="typeof product.rating === 'number'" class="tag-star">
                        ★ {{ product.rating }}<template v-if="product.rating_count">（{{ product.rating_count }}）</template>
                      </span>
                      <span v-if="product.available === true" class="tag-in">有货</span>
                    </p>
                    <div class="card-foot">
                      <a v-if="product.url" :href="product.url" target="_blank" rel="noopener">查看商品页 →</a>
                      <button
                        class="fav-btn fav-btn-sm"
                        :class="{ 'fav-btn-on': isFavorited(product.product_id) }"
                        type="button"
                        :disabled="favBusy === product.product_id"
                        @click="toggleFavorite(product)"
                      >
                        {{ isFavorited(product.product_id) ? '已收藏' : '收藏' }}
                      </button>
                    </div>
                  </div>
                </article>
              </div>
            </section>

            <p v-if="message.error" class="notice notice-error">{{ message.error }}</p>
          </div>
        </div>
      </div>
    </div>
    </div>

    <div class="composer-wrap">
      <div class="composer-inner">
        <div class="chips">
          <button
            v-for="sample in samples"
            :key="sample"
            type="button"
            class="chip"
            :disabled="sending"
            @click="useSample(sample)"
          >
            {{ sample }}
          </button>
        </div>

        <div class="composer">
          <textarea
            ref="textareaRef"
            v-model="input"
            rows="1"
            placeholder="说一句你想买什么，例如「500 以内的无线机械键盘」"
            @input="autoGrow"
            @keydown="onKeydown"
          ></textarea>
          <button class="send" type="button" :disabled="sending || !input.trim()" @click="onSend">
            {{ sending ? '···' : '↑' }}
          </button>
        </div>

        <p class="hint">回车发送 · Shift + 回车换行</p>
      </div>
    </div>
  </div>
</template>
