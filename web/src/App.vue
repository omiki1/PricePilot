<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'
import { fetchHealth, openChat } from './api.js'
import { renderMarkdown } from './markdown.js'

const userId = ref('u001')
const sessionId = ref('s001')
const input = ref('')
const showSettings = ref(false)

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

onMounted(async () => {
  try {
    health.value = await fetchHealth()
  } catch (exception) {
    health.value = { status: 'unreachable', error: exception.message }
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
                  <h3 class="pick-title" :title="product.title">{{ product.title }}</h3>

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
                    <a v-if="product.url" :href="product.url" target="_blank" rel="noopener">查看商品页 →</a>
                  </div>
                </article>
              </div>
            </section>

            <p v-if="message.error" class="notice notice-error">{{ message.error }}</p>
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
