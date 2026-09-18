<script setup>
import { computed, onMounted, ref } from 'vue'
import { fetchHealth, parseIntent, recognizeIntent, searchProducts } from './api.js'

const question = ref('我想买一个500以内的无线机械键盘')
const userId = ref('u001')
const sessionId = ref('s001')

const loading = ref(false)
const error = ref('')
const result = ref(null)      // /api/products/search 的完整返回
const health = ref(null)

const samples = [
  '我想买一个500以内的无线机械键盘',
  '我想买一个1000以内的无线耳机',
  '推荐个500块左右的机械键盘',
  '你好呀',
]

const summary = computed(() => (result.value?.text ? parseIntent(result.value.text) : null))
const products = computed(() => result.value?.products ?? [])

// 校验信息：条数 / 币种 / 价格区间 / 字段完整度
const stats = computed(() => {
  const list = products.value
  if (!list.length) return null
  const prices = list.map((item) => item.price).filter((value) => typeof value === 'number')
  const currencies = [...new Set(list.map((item) => item.currency).filter(Boolean))]
  return {
    total: list.length,
    currencies,
    min: prices.length ? Math.min(...prices) : null,
    max: prices.length ? Math.max(...prices) : null,
    available: list.filter((item) => item.available === true).length,
    withImage: list.filter((item) => item.image_url).length,
    withUrl: list.filter((item) => item.url).length,
    withRating: list.filter((item) => typeof item.rating === 'number').length,
    withSeller: list.filter((item) => item.seller).length,
  }
})

async function onSearch() {
  const text = question.value.trim()
  if (!text) {
    error.value = '请先输入你想买什么'
    return
  }
  loading.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await searchProducts({
      question: text,
      userId: userId.value,
      sessionId: sessionId.value,
    })
  } catch (exception) {
    error.value = exception.message || '请求失败'
  } finally {
    loading.value = false
  }
}

async function onIntentOnly() {
  const text = question.value.trim()
  if (!text) {
    error.value = '请先输入你想买什么'
    return
  }
  loading.value = true
  error.value = ''
  result.value = null
  try {
    const payload = await recognizeIntent({
      question: text,
      userId: userId.value,
      sessionId: sessionId.value,
    })
    result.value = { ...payload, products: [] }
  } catch (exception) {
    error.value = exception.message || '请求失败'
  } finally {
    loading.value = false
  }
}

function priceText(product) {
  if (product.price === null || product.price === undefined) return '价格待确认'
  return `${product.currency || ''} ${product.price}`.trim()
}

function onImageError(event) {
  event.target.style.display = 'none'
}

onMounted(async () => {
  try {
    health.value = await fetchHealth()
  } catch (exception) {
    health.value = { status: 'unreachable', error: exception.message }
  }
})
</script>

<template>
  <main class="page">
    <header class="header">
      <h1>PricePilot · 意图识别 + Shopify 检索</h1>
      <p class="subtitle">
        验证链路：意图识别（START → intent → shopify_search）→ Shopify catalog MCP → 前端展示。
      </p>
      <span class="badge" :class="health && health.status === 'ok' ? 'badge-ok' : 'badge-bad'">
        后端：{{ health ? health.status : '检测中' }}
        <template v-if="health && health.components"> · graph：{{ health.components.graph ? '已装配' : '未装配' }}</template>
      </span>
    </header>

    <section class="card">
      <label class="field">
        <span>你想买什么</span>
        <textarea v-model="question" rows="3" placeholder="例如：我想买一个500以内的无线机械键盘"></textarea>
      </label>

      <div class="row">
        <label class="field">
          <span>用户 ID</span>
          <input v-model="userId" type="text" />
        </label>
        <label class="field">
          <span>会话 ID</span>
          <input v-model="sessionId" type="text" />
        </label>
      </div>

      <div class="samples">
        <button v-for="sample in samples" :key="sample" type="button" class="chip" @click="question = sample">
          {{ sample }}
        </button>
      </div>

      <div class="actions">
        <button class="primary" type="button" :disabled="loading" @click="onIntentOnly">
          {{ loading ? '处理中…' : '只做意图识别' }}
        </button>
        <button class="primary ghost" type="button" :disabled="loading" @click="onSearch">
          {{ loading ? '检索中…' : '识别并查 Shopify 商品' }}
        </button>
      </div>
    </section>

    <p v-if="error" class="error">{{ error }}</p>

    <section v-if="result" class="card result">
      <h2>链路第一步：意图识别</h2>
      <div class="fields">
        <div class="field-item">
          <span class="field-label">商品类型（→ Shopify query）</span>
          <strong>{{ result.category || summary?.category || '未提到' }}</strong>
        </div>
        <div class="field-item">
          <span class="field-label">预算（→ filters.price.max）</span>
          <strong>{{ result.price ? result.price : '未提到' }}</strong>
        </div>
      </div>
      <pre class="raw">{{ result.text }}</pre>
      <small class="meta">user_id={{ result.user_id }} · session_id={{ result.session_id }}</small>
    </section>

    <section v-if="stats" class="card">
      <h2>链路第二步：Shopify 返回校验</h2>
      <div class="stat-grid">
        <div class="stat"><span class="field-label">商品数</span><strong>{{ stats.total }}</strong></div>
        <div class="stat"><span class="field-label">币种</span><strong>{{ stats.currencies.join(' / ') || '—' }}</strong></div>
        <div class="stat">
          <span class="field-label">价格区间</span>
          <strong>{{ stats.min !== null ? `${stats.min} ~ ${stats.max}` : '—' }}</strong>
        </div>
        <div class="stat"><span class="field-label">有货</span><strong>{{ stats.available }} / {{ stats.total }}</strong></div>
        <div class="stat"><span class="field-label">带图片</span><strong>{{ stats.withImage }} / {{ stats.total }}</strong></div>
        <div class="stat"><span class="field-label">带商品链接</span><strong>{{ stats.withUrl }} / {{ stats.total }}</strong></div>
        <div class="stat"><span class="field-label">有评分</span><strong>{{ stats.withRating }} / {{ stats.total }}</strong></div>
        <div class="stat"><span class="field-label">有卖家</span><strong>{{ stats.withSeller }} / {{ stats.total }}</strong></div>
      </div>
      <p v-if="result.price && !stats.currencies.includes('CNY')" class="notice notice-warn">
        注意：意图里的预算是 <strong>{{ result.price }}</strong>，而 Shopify 返回的币种是
        <strong>{{ stats.currencies.join('/') }}</strong>。两者币种不同，不能直接比较
        —— 后端把预算按<em>分</em>传给 Shopify（{{ Math.round(result.price * 100) }}），没有做汇率换算。
      </p>
    </section>

    <section v-if="products.length" class="card">
      <h2>商品列表（{{ products.length }} 条）</h2>
      <div class="grid">
        <article v-for="product in products" :key="product.product_id" class="offer">
          <img
            v-if="product.image_url"
            :src="product.image_url"
            :alt="product.title"
            loading="lazy"
            @error="onImageError"
          />
          <div v-else class="image-placeholder">暂无图片</div>
          <div class="offer-body">
            <h3 :title="product.title">{{ product.title }}</h3>
            <strong class="price">{{ priceText(product) }}</strong>
            <p class="offer-meta">
              <template v-if="product.seller">{{ product.seller }}</template>
              <template v-if="product.seller && product.platform"> · </template>
              <template v-if="product.platform">{{ product.platform }}</template>
            </p>
            <p class="offer-tags">
              <span v-if="typeof product.rating === 'number'">
                ★ {{ product.rating }}<template v-if="product.rating_count">（{{ product.rating_count }}）</template>
              </span>
              <span v-if="product.available === true">有货</span>
              <span v-else-if="product.available === false">缺货</span>
              <span v-if="product.currency">{{ product.currency }}</span>
            </p>
            <a v-if="product.url" :href="product.url" target="_blank" rel="noopener">查看商品页</a>
            <small class="meta">id=…{{ String(product.product_id).slice(-10) }}</small>
          </div>
        </article>
      </div>
    </section>

    <p v-else-if="result && !loading" class="card meta">
      本次没有返回商品。可能原因：Shopify MCP 没匹配到结果、网络失败，或意图里的商品类型为空。
    </p>
  </main>
</template>
