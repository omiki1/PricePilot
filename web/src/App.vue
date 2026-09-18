<script setup>
import { computed, onMounted, ref } from 'vue'
import { fetchHealth, fetchSources, parseIntent, recognizeIntent, searchProducts } from './api.js'

const question = ref('我想买一个1000以内的无线耳机')
const userId = ref('u001')
const sessionId = ref('s001')

const loading = ref(false)
const error = ref('')
const result = ref(null)
const health = ref(null)
const sourceInfo = ref({ enabled: [], items: [], cache: null })

// 检索状态
const keyword = ref('耳机')
const sources = ref([])        // 选中的来源
const searching = ref(false)
const searchError = ref('')
const results = ref([])
const searchedAt = ref('')
const cacheInfo = ref(null)

const samples = [
  '我想买一个1000以内的无线耳机',
  '推荐个500块左右的机械键盘',
  '一千到两千的显示器',
  '你好呀',
]

const summary = computed(() => (result.value ? parseIntent(result.value.text) : null))
const totalOffers = computed(() => results.value.reduce((sum, item) => sum + (item.offers?.length ?? 0), 0))

function platformOf(name) {
  const item = sourceInfo.value.items.find((entry) => entry.name === name)
  return item ? item.platform : name
}

function costNoteOf(name) {
  const item = sourceInfo.value.items.find((entry) => entry.name === name)
  return item?.cost_note || ''
}

function toggleSource(name) {
  const index = sources.value.indexOf(name)
  if (index === -1) sources.value.push(name)
  else sources.value.splice(index, 1)
}

function priceText(offer) {
  if (offer.price === null || offer.price === undefined) return '价格待确认'
  return `${offer.currency} ${offer.price}`
}

function statusText(outcome) {
  const labels = {
    completed: '完成',
    not_configured: '未配置',
    needs_session: '需要登录态',
    failed: '失败',
    timeout: '超时',
  }
  return labels[outcome.status] || outcome.status
}

async function onRecognize() {
  const text = question.value.trim()
  if (!text) {
    error.value = '请先输入你想买什么'
    return
  }
  loading.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await recognizeIntent({
      question: text,
      userId: userId.value,
      sessionId: sessionId.value,
    })
    const parsed = parseIntent(result.value.text)
    if (parsed.category && parsed.category !== '未提到商品') {
      keyword.value = parsed.category
    }
  } catch (exception) {
    error.value = exception.message || '请求失败'
  } finally {
    loading.value = false
  }
}

async function onSearch() {
  const text = keyword.value.trim()
  if (!text) {
    searchError.value = '请先输入检索关键词'
    return
  }
  if (!sources.value.length) {
    searchError.value = '至少选择一个来源'
    return
  }
  searching.value = true
  searchError.value = ''
  results.value = []
  try {
    const payload = await searchProducts({ keyword: text, sources: sources.value, limit: 6 })
    results.value = payload.results || []
    cacheInfo.value = payload.cache || null
    searchedAt.value = new Date().toLocaleTimeString()
  } catch (exception) {
    searchError.value = exception.message || '检索失败'
  } finally {
    searching.value = false
  }
}

async function onIntentThenSearch() {
  await onRecognize()
  if (!error.value) await onSearch()
}

onMounted(async () => {
  try {
    health.value = await fetchHealth()
  } catch (exception) {
    health.value = { status: 'unreachable', error: exception.message }
  }
  try {
    sourceInfo.value = await fetchSources()
    sources.value = [...(sourceInfo.value.enabled || [])]
  } catch (exception) {
    sourceInfo.value = { enabled: [], items: [], error: exception.message }
  }
})
</script>

<template>
  <main class="page">
    <header class="header">
      <h1>PricePilot · 意图识别 + 商品检索</h1>
      <p class="subtitle">
        已接通：意图识别节点（START → intent → END）+ 商品来源（Apify actor，当前启用：{{ sourceInfo.enabled.join('、') || '无' }}）。
      </p>
      <span class="badge" :class="health && health.status === 'ok' ? 'badge-ok' : 'badge-bad'">
        后端：{{ health ? health.status : '检测中' }}
        <template v-if="health && health.components && health.components.sources">
          · 来源：<template v-for="(ok, name) in health.components.sources" :key="name">{{ name }}={{ ok ? '已配' : '未配' }} </template>
        </template>
      </span>
    </header>

    <section class="card">
      <label class="field">
        <span>你想买什么</span>
        <textarea v-model="question" rows="3" placeholder="例如：我想买一个1000以内的无线耳机"></textarea>
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
        <button class="primary" type="button" :disabled="loading" @click="onRecognize">
          {{ loading ? '识别中…' : '只做意图识别' }}
        </button>
        <button class="primary ghost" type="button" :disabled="loading || searching" @click="onIntentThenSearch">
          {{ loading || searching ? '处理中…' : '识别并查商品' }}
        </button>
      </div>
    </section>

    <p v-if="error" class="error">{{ error }}</p>

    <section v-if="result" class="card result">
      <h2>意图识别结果</h2>
      <div v-if="summary" class="fields">
        <div class="field-item">
          <span class="field-label">商品类型</span>
          <strong>{{ summary.category }}</strong>
        </div>
        <div class="field-item">
          <span class="field-label">价格</span>
          <strong>{{ summary.price }}</strong>
        </div>
      </div>
      <pre class="raw">{{ result.text }}</pre>
      <small class="meta">user_id={{ result.user_id }} · session_id={{ result.session_id }}</small>
    </section>

    <section class="card">
      <h2>商品检索</h2>

      <div class="searchbar">
        <input v-model="keyword" type="text" placeholder="检索关键词，例如：无线耳机" @keyup.enter="onSearch" />
        <button class="primary" type="button" :disabled="searching" @click="onSearch">
          {{ searching ? '检索中…' : '查商品' }}
        </button>
      </div>

      <div class="sources">
        <span class="meta">来源：</span>
        <button
          v-for="item in sourceInfo.items"
          :key="item.name"
          type="button"
          class="chip"
          :class="{ 'chip-on': sources.includes(item.name) }"
          :title="item.cost_note || ''"
          @click="toggleSource(item.name)"
        >
          {{ sources.includes(item.name) ? '✓ ' : '' }}{{ item.platform }}
        </button>
        <span v-if="searchedAt" class="meta">· 检索于 {{ searchedAt }} · 共 {{ totalOffers }} 条</span>
      </div>

      <p v-for="name in sources" :key="'cost-' + name" class="cost-note">💰 {{ costNoteOf(name) }}</p>
      <p v-if="cacheInfo" class="meta">
        本次缓存：命中 {{ cacheInfo.hit.join('、') || '无' }}；实跑 {{ cacheInfo.miss.join('、') || '无' }}（TTL {{ cacheInfo.ttl_seconds }}s，命中即不重复计费）
      </p>

      <p v-if="searchError" class="error">{{ searchError }}</p>

      <template v-for="outcome in results" :key="outcome.source">
        <div class="source-block">
          <div class="source-head">
            <h3>{{ platformOf(outcome.source) }}</h3>
            <span class="tag" :class="outcome.status === 'completed' ? 'tag-ok' : 'tag-warn'">
              {{ statusText(outcome) }} · {{ outcome.offers.length }} 条 · mode={{ outcome.mode }}
            </span>
          </div>

          <p v-if="outcome.message" class="notice" :class="outcome.status === 'completed' ? 'notice-warn' : 'notice-ok'">
            {{ outcome.message }}
          </p>

          <div v-if="outcome.offers.length" class="grid">
            <article v-for="offer in outcome.offers" :key="offer.source_id" class="offer">
              <img v-if="offer.image_url" :src="offer.image_url" :alt="offer.title" loading="lazy" />
              <div v-else class="image-placeholder">暂无图片</div>
              <div class="offer-body">
                <h3 :title="offer.title">{{ offer.title }}</h3>
                <strong class="price">{{ priceText(offer) }}</strong>
                <p v-if="offer.coupon_price" class="meta coupon">券后 {{ offer.currency }} {{ offer.coupon_price }}</p>
                <p v-else-if="offer.list_price" class="meta">原价 {{ offer.currency }} {{ offer.list_price }}</p>
                <p class="offer-meta">
                  <template v-if="offer.brand">{{ offer.brand }} · </template>
                  <template v-if="offer.shop_name">{{ offer.shop_name }} · </template>
                  <template v-if="offer.city">{{ offer.city }}</template>
                </p>
                <p class="offer-tags">
                  <span v-if="offer.is_tmall">天猫</span>
                  <span v-if="offer.sales !== null && offer.sales !== undefined">销量 {{ offer.sales }}</span>
                  <span v-if="offer.reviews_count !== null && offer.reviews_count !== undefined">评论 {{ offer.reviews_count }}</span>
                  <span v-if="offer.sku_count">SKU {{ offer.sku_count }}</span>
                  <span v-if="offer.in_stock === true">有货</span>
                  <span v-if="offer.in_stock === false">缺货</span>
                  <span v-if="offer.rating">★ {{ offer.rating }}</span>
                  <span v-if="offer.free_shipping">包邮</span>
                  <span class="mode-tag">{{ offer.data_mode }}</span>
                </p>
                <a :href="offer.url" target="_blank" rel="noopener">查看商品页</a>
              </div>
            </article>
          </div>
          <p v-else class="meta">该来源本次没有可展示的商品。</p>

          <p v-if="outcome.compliance_note" class="compliance">⚠️ {{ outcome.compliance_note }}</p>
        </div>
      </template>

      <p v-if="!results.length && !searching" class="meta">
        还没检索。上面识别出商品类型后点「识别并查商品」，或在这里直接输入关键词。
      </p>
      <p class="meta">不同来源的币种可能不同（CNY / USD），按手册口径各自展示，不做跨币种比价与排序。</p>
    </section>
  </main>
</template>
