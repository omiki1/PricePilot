<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import {
  addFavorite,
  fetchFavorites,
  fetchHealth,
  fetchPriceHistory,
  openChat,
  removeFavorite,
} from './api.js'
import LoginView from './LoginView.vue'

// ---- 登录态 ----
// 存 localStorage，刷新页面不用重登。
// 注意：这只是"记住你是谁"，不是安全凭证 —— 后端接口目前仍接受前端传的 user_id，
// 真正的鉴权要等 token/session 做出来（那时这里换成存 token）。
const USER_KEY = 'pricepilot.user'

function loadStoredUser() {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch (exception) {
    // localStorage 被禁用或内容损坏，当没登录处理，不让它把整个应用搞崩
    return null
  }
}

const currentUser = ref(loadStoredUser())
const showLogin = ref(false)
// 登录后 user_id 用后端的 user_id：收藏归属跟着账号走
const userId = ref(currentUser.value ? String(currentUser.value.user_id) : 'u001')
const sessionId = ref('s001')
const input = ref('')
const showSettings = ref(false)

const messages = ref([])          // {role, text, products, streaming, error, showAll}
const sending = ref(false)
const health = ref(null)
const scrollRef = ref(null)
const textareaRef = ref(null)
const failedImages = reactive(new Set())

// ---- 收藏 ----
const favorites = ref([])         // 收藏夹（后端返回的快照）
const favoritesTotal = ref(0)
const showFavorites = ref(false)
const favoritesError = ref('')
const favoritesLoading = ref(false)
const pendingProductIds = reactive(new Set())   // 正在请求中的商品，按钮转圈并防连点
const favoriteNotice = ref('')                  // 收藏失败/未配置时的提示

// 价格记录：点「价格记录」才去查，不在收藏列表里预加载。
// 一次只展开一个商品，key 是 product_id，值是 { loading, error, points }。
const pricePanels = reactive({})

// 已收藏的商品 id 集合：决定每张卡上的按钮是空心还是实心
const favoriteIds = computed(() => new Set(favorites.value.map((item) => item.product_id)))
const favoritesReady = computed(() => health.value?.components?.favorites !== false)

const samples = [
  '我想买一个500以内的无线机械键盘',
  '15000以内的Ibanez电吉他',
  '我想买一台游戏机',
  '推荐个500块左右的显示器',
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
  if (product.price === null || product.price === undefined) return '价格待确认'
  return `${product.currency || ''} ${product.price}`.trim()
}

function scoreText(product) {
  return product.score === null || product.score === undefined ? '' : `加权 ${product.score}`
}

function imageFailed(product) {
  return failedImages.has(product.product_id)
}

function markImageFailed(product) {
  failedImages.add(product.product_id)
}

// 只递回后端真正会落库的字段。证据、评分理由这些不存，传了也是白传。
function toFavoritePayload(product) {
  return {
    product_id: product.product_id,
    title: product.title,
    price: product.price,
    image_url: product.image_url,
    url: product.url,
  }
}

function isFavorited(product) {
  return favoriteIds.value.has(product.product_id)
}

function isPending(product) {
  return pendingProductIds.has(product.product_id)
}

async function loadFavorites() {
  favoritesLoading.value = true
  try {
    const data = await fetchFavorites({ userId: userId.value })
    favorites.value = data.favorites || []
    favoritesTotal.value = data.total || 0
    favoritesError.value = ''
  } catch (exception) {
    favoritesError.value = exception.message
  } finally {
    favoritesLoading.value = false
  }
}

async function toggleFavorite(product) {
  const productId = product.product_id
  if (!productId || pendingProductIds.has(productId)) return

  pendingProductIds.add(productId)
  favoriteNotice.value = ''
  try {
    if (isFavorited(product)) {
      await removeFavorite({ userId: userId.value, productId })
    } else {
      await addFavorite({ userId: userId.value, product: toFavoritePayload(product) })
    }
    await loadFavorites()
  } catch (exception) {
    favoriteNotice.value = exception.message
  } finally {
    pendingProductIds.delete(productId)
  }
}

async function toggleFavoritesPanel() {
  showFavorites.value = !showFavorites.value
  if (showFavorites.value) await loadFavorites()
}

async function removeFromPanel(item) {
  if (pendingProductIds.has(item.product_id)) return
  pendingProductIds.add(item.product_id)
  favoriteNotice.value = ''
  try {
    await removeFavorite({ userId: userId.value, productId: item.product_id })
    await loadFavorites()
  } catch (exception) {
    favoriteNotice.value = exception.message
  } finally {
    pendingProductIds.delete(item.product_id)
  }
}

// 单个收藏项的时间：后端给的是 UTC ISO 串，转成本地可读
function favoriteTime(item) {
  if (!item.time) return ''
  const parsed = new Date(item.time)
  if (Number.isNaN(parsed.getTime())) return item.time
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

// ---- 价格记录 ----
// 只把价格按时间列出来，不算涨跌、不判历史最低价 ——
// 样本太少时那种结论本身就是误导。

// 收藏表不存币种，这里只显示数字，不硬编一个"元"或"$"上去。
function favoritePrice(item) {
  if (item.price === null || item.price === undefined) return '价格待确认'
  return String(item.price)
}

function pricePanel(item) {
  return pricePanels[item.product_id] || null
}

// 点「价格记录」：展开并拉数据；再点一次收起。已加载过的直接显示，不重复请求。
async function togglePricePanel(item) {
  const productId = item.product_id
  const current = pricePanels[productId]

  if (current && !current.collapsed) {
    current.collapsed = true
    return
  }
  if (current && current.points) {          // 之前查过，直接展开
    current.collapsed = false
    return
  }

  pricePanels[productId] = { collapsed: false, loading: true, error: '', points: [] }
  try {
    const data = await fetchPriceHistory({ productId })
    pricePanels[productId] = {
      collapsed: false, loading: false, error: '', points: data.points || [],
    }
  } catch (exception) {
    pricePanels[productId] = {
      collapsed: false, loading: false, error: exception.message, points: [],
    }
  }
}

// 单个价格点的显示：金额 + 本地时间（后端给的是 UTC ISO 串）
function pointTime(point) {
  const parsed = new Date(point.recorded_at)
  if (Number.isNaN(parsed.getTime())) return point.recorded_at
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

// ---- 登录 ----
// 登录后 user_id 用后端的 user_id，收藏夹随之切换成这个账号的
async function onLoggedIn(user) {
  currentUser.value = user || null
  showLogin.value = false
  if (user && user.user_id !== undefined && user.user_id !== null) {
    userId.value = String(user.user_id)
  }
  try {
    localStorage.setItem(USER_KEY, JSON.stringify(currentUser.value))
  } catch (exception) {
    // 隐私模式下 localStorage 可能写不了，不影响本次登录
  }
  messages.value = []          // 换账号就不该看到上一个会话的记录
  pricePanels.value = {}       // 展开的价格面板也清掉
  await loadFavorites()
}

function logout() {
  currentUser.value = null
  showLogin.value = true
  try {
    localStorage.removeItem(USER_KEY)
  } catch (exception) {
    // 同上，删不掉也不影响
  }
  favorites.value = []
  favoritesTotal.value = 0
  messages.value = []
  pricePanels.value = {}
}

onMounted(async () => {
  try {
    health.value = await fetchHealth()
  } catch (exception) {
    health.value = { status: 'unreachable', error: exception.message }
  }
  // 有登录态（可能是上次留下的）才拉收藏：user_id 要对得上才有意义
  if (currentUser.value && health.value?.components?.favorites) {
    await loadFavorites()
  }
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
        <button
          class="settings-toggle"
          type="button"
          :title="showFavorites ? '收起左侧收藏栏' : '展开左侧收藏栏'"
          @click="toggleFavoritesPanel"
        >
          {{ showFavorites ? '‹' : '›' }} 收藏夹{{ favoritesTotal ? ' ' + favoritesTotal : '' }}
        </button>
        <button class="settings-toggle" type="button" @click="showSettings = !showSettings">
          {{ showSettings ? '收起设置' : '会话设置' }}
        </button>
        <button v-if="currentUser" class="settings-toggle" type="button" @click="logout" :title="userId">
          退出（{{ currentUser.username }}）
        </button>
        <button v-else class="settings-toggle" type="button" @click="showLogin = true">
          登录
        </button>
      </div>
    </header>

    <!-- 未登录 / 主动点登录时，盖一层登录页 -->
    <LoginView
      v-if="showLogin || !currentUser"
      class="login-overlay"
      @logged-in="onLoggedIn"
    />

    <div v-if="showSettings" class="settings">
      <label class="field">
        <span>用户 ID（收藏归属，换一个就是另一份收藏夹）</span>
        <input v-model="userId" type="text" @change="loadFavorites" />
      </label>
      <label class="field">
        <span>会话 ID（同一 ID 共享图状态）</span>
        <input v-model="sessionId" type="text" />
      </label>
    </div>

    <div class="main">
      <!-- 左侧收藏栏：只做读库展示 + 取消收藏，
           收藏这个动作始终在商品卡的按钮上，这里不提供"添加"入口 -->
      <aside v-if="showFavorites" class="fav-side">
        <div class="fav-side-head">
          <h3>我的收藏</h3>
          <span class="section-note">{{ favoritesTotal }} 件</span>
          <button class="fav-side-close" type="button" title="收起收藏栏" @click="toggleFavoritesPanel">‹</button>
        </div>

        <p v-if="favoritesLoading" class="fav-side-hint">正在读取…</p>
        <p v-else-if="favoritesError" class="fav-side-error">{{ favoritesError }}</p>
        <div v-else-if="!favorites.length" class="fav-side-hint">
          <p>还没有收藏。</p>
          <p>搜索出商品后，点卡片上的「☆ 收藏」。</p>
        </div>

        <div v-else class="fav-side-list">
          <article v-for="item in favorites" :key="item.id" class="fav-side-item">
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
              <h4 class="fav-side-title" :title="item.title">{{ item.title }}</h4>
              <p class="fav-side-line">
                <strong class="fav-side-price">
                  {{ favoritePrice(item) }}
                </strong>
                <span class="fav-side-time">{{ favoriteTime(item) }}</span>
              </p>

              <div class="fav-side-actions">
                <button
                  class="fav-side-link"
                  type="button"
                  :class="{ 'fav-side-link-open': pricePanel(item) && !pricePanel(item).collapsed }"
                  @click="togglePricePanel(item)"
                >
                  价格记录
                </button>
                <a v-if="item.product_url" :href="item.product_url" target="_blank" rel="noopener">商品页 →</a>
                <button
                  class="fav-side-remove"
                  type="button"
                  :disabled="pendingProductIds.has(item.product_id)"
                  @click="removeFromPanel(item)"
                >
                  {{ pendingProductIds.has(item.product_id) ? '···' : '取消收藏' }}
                </button>
              </div>

              <!-- 价格记录：点上面的「价格记录」才展开，数据也是那时才请求 -->
              <div v-if="pricePanel(item) && !pricePanel(item).collapsed" class="price-panel">
                <p v-if="pricePanel(item).loading" class="price-empty">正在读取…</p>
                <p v-else-if="pricePanel(item).error" class="price-error">{{ pricePanel(item).error }}</p>

                <template v-else>
                  <!-- 只列价格：时间 + 金额，从上往下按时间排 -->
                  <ul v-if="pricePanel(item).points.length" class="price-list">
                    <li v-for="(point, i) in pricePanel(item).points" :key="i">
                      <span class="price-when">{{ pointTime(point) }}</span>
                      <span class="price-amount">{{ point.price }}</span>
                    </li>
                  </ul>
                  <p v-else class="price-empty">还没有价格记录，收藏时会自动记一笔。</p>
                </template>
              </div>
            </div>
          </article>
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
              正在理解需求并检索商品…
            </div>

            <div v-if="message.text" class="text">{{ message.text }}<span v-if="message.streaming" class="caret"></span></div>

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
                      :class="{ 'fav-btn-on': isFavorited(product) }"
                      type="button"
                      :disabled="isPending(product) || !product.product_id || !favoritesReady"
                      :title="favoritesReady ? (isFavorited(product) ? '点击取消收藏' : '点击加入收藏') : '收藏功能不可用：后端没连上收藏表'"
                      @click="toggleFavorite(product)"
                    >
                      {{ isPending(product) ? '···' : (isFavorited(product) ? '★ 已收藏' : '☆ 收藏') }}
                    </button>
                  </div>

                  <p class="pick-line">
                    <strong class="pick-price">{{ priceText(product) }}</strong>
                    <span v-if="scoreText(product)" class="pick-score">{{ scoreText(product) }}</span>
                    <span v-if="typeof product.rating === 'number'" class="pick-rating">
                      ★ {{ product.rating }}<template v-if="product.rating_count">（{{ product.rating_count }}）</template>
                    </span>
                    <span v-if="product.available === true" class="pick-stock">有货</span>
                  </p>

                  <p class="pick-meta">{{ [product.seller, product.platform].filter(Boolean).join(' · ') }}</p>

                  <!-- 证据：编号和文字里的 [S11] 对应 -->
                  <details v-if="(product.evidence || []).length" class="evidence">
                    <summary>第三方证据 {{ product.evidence.length }} 条（对应正文里的编号）</summary>
                    <ul>
                      <li v-for="item in product.evidence" :key="item.id || item.url">
                        <span class="ev-id">[{{ item.id || 'S' }}]</span>
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
                        :class="{ 'fav-btn-on': isFavorited(product) }"
                        type="button"
                        :disabled="isPending(product) || !product.product_id || !favoritesReady"
                        @click="toggleFavorite(product)"
                      >
                        {{ isPending(product) ? '···' : (isFavorited(product) ? '★ 已收藏' : '☆ 收藏') }}
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
        <p v-if="favoriteNotice" class="notice notice-error">{{ favoriteNotice }}</p>
        <p v-else-if="health && health.components && health.components.favorites === false" class="notice notice-warn">
          收藏功能不可用：后端没有连上收藏表（可能是 MySQL 没起来，或 favorite_product 表还没建）。
        </p>

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

        <p class="hint">回车发送 · Shift + 回车换行 · 收藏是卡片右上角的按钮，不用打字</p>
      </div>
    </div>
  </div>
</template>
