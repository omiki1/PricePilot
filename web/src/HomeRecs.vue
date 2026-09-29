<script setup>
// 新对话空白页的推荐区（omiki 2026-09-29）
// 文案全部来自 ui_copy.js；推荐理由用 recReason(match) 拼，match 由后端 /api/recommendations 给。
// 一行 4 张卡：后端一次最多给 8 件，「换一批」先在本地翻到后 4 件，翻完了才请求 refresh=1。
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { fetchRecommendations } from './api.js'
import { EMPTY_STATE, ERRORS, recReason } from './ui_copy.js'

const props = defineProps({
  userId: { type: String, required: true },
  favoriteIds: { type: Array, default: () => [] },
  favBusy: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['toggle-favorite', 'pick', 'send'])

const PAGE_SIZE = 4

const loading = ref(true)
const refreshing = ref(false)
const failed = ref(false)          // 网络层失败，或后端 error=true
const exhausted = ref(false)
const mode = ref('samples')
const products = ref([])
const page = ref(0)
const brokenImages = reactive(new Set())

const visible = computed(() => products.value.slice(page.value * PAGE_SIZE, (page.value + 1) * PAGE_SIZE))
const hasCards = computed(() => mode.value !== 'samples' && products.value.length > 0)
const heading = computed(() => {
  if (loading.value) return ''
  if (!hasCards.value) return EMPTY_STATE.recTitle.none
  return EMPTY_STATE.recTitle[mode.value] || EMPTY_STATE.recTitle.none
})

function apply(data) {
  mode.value = data.mode || 'samples'
  products.value = data.products || []
  failed.value = Boolean(data.error)
  page.value = 0
}

async function load() {
  loading.value = true
  exhausted.value = false
  try {
    apply(await fetchRecommendations({ userId: props.userId }))
  } catch (error) {
    mode.value = 'samples'
    products.value = []
    failed.value = true
  } finally {
    loading.value = false
  }
}

async function refresh() {
  if (refreshing.value) return
  exhausted.value = false
  // 这一批还有没看过的：直接翻页，不打后端
  if ((page.value + 1) * PAGE_SIZE < products.value.length) {
    page.value += 1
    return
  }
  refreshing.value = true
  try {
    const data = await fetchRecommendations({ userId: props.userId, refresh: true })
    if (data.error || data.mode === 'samples' || !(data.products || []).length) {
      // 换一批失败或没结果：保留当前这批，只提示一句，不把卡片清空
      exhausted.value = true
      page.value = 0
    } else {
      apply(data)
      exhausted.value = Boolean(data.exhausted)
    }
  } catch (error) {
    exhausted.value = true
    page.value = 0
  } finally {
    refreshing.value = false
  }
}

function reason(product) {
  return recReason(product.match || {})
}

// price_text 形如「USD 56.98 / 人民币 ≈ ¥383.16」：卡片窄，拆成主价 + 一行灰色的人民币估算
function priceMain(product) {
  return (product.price_text || '价格待确认').split(' / ')[0]
}

function priceSub(product) {
  return (product.price_text || '').split(' / ').slice(1).join(' / ')
}

function isFavorited(product) {
  return props.favoriteIds.includes(product.product_id)
}

watch(() => props.userId, load)
onMounted(load)
</script>

<template>
  <section class="recs" aria-live="polite">
    <div class="recs-head">
      <h4 v-if="loading" class="recs-title recs-title-skeleton"></h4>
      <h4 v-else class="recs-title">{{ heading }}</h4>
      <button
        v-if="hasCards"
        class="recs-refresh"
        type="button"
        :disabled="refreshing"
        @click="refresh"
      >
        <span class="recs-refresh-icon" :class="{ spinning: refreshing }">↻</span>
        {{ refreshing ? EMPTY_STATE.refreshing : EMPTY_STATE.refresh }}
      </button>
    </div>

    <!-- 加载骨架：和真卡片同尺寸，避免加载完跳动 -->
    <div v-if="loading" class="recs-grid">
      <div v-for="n in 4" :key="n" class="rec-card rec-skeleton">
        <div class="rec-thumb"></div>
        <div class="rec-body">
          <span class="sk-line"></span>
          <span class="sk-line sk-short"></span>
          <span class="sk-chip"></span>
        </div>
      </div>
    </div>

    <template v-else-if="hasCards">
      <div class="recs-grid">
        <article
          v-for="product in visible"
          :key="product.product_id"
          class="rec-card"
          :title="EMPTY_STATE.cardHint"
        >
          <button class="rec-main" type="button" :disabled="disabled" @click="emit('pick', product)">
            <div class="rec-thumb">
              <img
                v-if="product.image_url && !brokenImages.has(product.product_id)"
                :src="product.image_url"
                :alt="product.title"
                loading="lazy"
                @error="brokenImages.add(product.product_id)"
              />
              <span v-else>暂无图片</span>
            </div>
            <div class="rec-body">
              <h3 class="rec-title">{{ product.title }}</h3>
              <p class="rec-price">
                {{ priceMain(product) }}
                <span v-if="priceSub(product)" class="rec-price-sub">{{ priceSub(product) }}</span>
              </p>
              <span v-if="reason(product)" class="rec-reason">{{ reason(product) }}</span>
            </div>
          </button>
          <button
            class="fav-btn fav-btn-sm rec-fav"
            :class="{ 'fav-btn-on': isFavorited(product) }"
            type="button"
            :disabled="favBusy === product.product_id"
            @click.stop="emit('toggle-favorite', product)"
          >
            {{ isFavorited(product) ? '已收藏' : '收藏' }}
          </button>
        </article>
      </div>
      <p v-if="exhausted" class="recs-note">{{ EMPTY_STATE.refreshExhausted }}</p>
    </template>

    <!-- 没画像也没收藏，或推荐挂了：给 4 个示例问题，点了直接发送 -->
    <template v-else>
      <p v-if="failed" class="recs-note recs-note-warn">{{ ERRORS.recFailed }}</p>
      <div class="recs-samples">
        <button
          v-for="question in EMPTY_STATE.sampleQuestions"
          :key="question"
          class="recs-sample"
          type="button"
          :disabled="disabled"
          @click="emit('send', question)"
        >
          {{ question }}
          <span class="recs-sample-arrow">→</span>
        </button>
      </div>
    </template>
  </section>
</template>
