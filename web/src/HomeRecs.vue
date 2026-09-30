<script setup>
// 新对话空白页的推荐区（omiki 2026-09-29）
// 文案全部来自 ui_copy.js；推荐理由用 recReason(match) 拼，match 由后端 /api/recommendations 给。
// 一行 4 张卡：后端一次最多给 8 件，「换一批」先在本地翻到后 4 件，翻完了才请求 refresh=1。
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
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

// 翻面动画的三个时间参数，改 CSS 的 .rec-flip transition 时要一起改
const FLIP_MS = 560          // 单张牌翻转时长
const STAGGER_MS = 70        // 每张牌依次错开，做出"发牌"的手感
const FLIP_TOTAL = FLIP_MS + STAGGER_MS * PAGE_SIZE + 60

const loading = ref(true)
const refreshing = ref(false)
const failed = ref(false)          // 网络层失败，或后端 error=true
const exhausted = ref(false)
const mode = ref('samples')
const products = ref([])
const page = ref(0)
const brokenImages = reactive(new Set())

// ── 翻面状态 ────────────────────────────────────────────────
const flipping = ref(false)        // 正在翻
const instant = ref(false)         // 归零那一帧禁用过渡，否则牌会自己转回来
const pending = ref([])            // 背面那一批；为空时背面是空的，不会翻出白牌

// 系统开了"减少动态效果"就跳过等待，逻辑照常走，只是不做动画
const reducedMotion =
  typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : false

const visible = computed(() => products.value.slice(page.value * PAGE_SIZE, (page.value + 1) * PAGE_SIZE))
const hasCards = computed(() => mode.value !== 'samples' && products.value.length > 0)
const heading = computed(() => {
  if (loading.value) return ''
  if (!hasCards.value) return EMPTY_STATE.recTitle.none
  return EMPTY_STATE.recTitle[mode.value] || EMPTY_STATE.recTitle.none
})

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** 每张牌的延迟：翻的时候依次错开，归零那一帧不需要延迟。 */
function flipStyle(index) {
  return { transitionDelay: flipping.value ? `${index * STAGGER_MS}ms` : '0ms' }
}

/** 一张牌的两个面：正面是当前这批，背面是待换上来的那批。 */
function facesFor(index) {
  return [
    { side: 'front', product: visible.value[index] },
    { side: 'back', product: pending.value[index] },
  ]
}

/**
 * 翻一次牌。
 *
 * 顺序很重要：必须等背面**渲染出来**再开始转，否则会翻出一张白牌。
 * 转完之后把内容换成新的、并把 rotateY 瞬间归零 —— 归零那一帧必须禁用过渡，
 * 不然牌会当着用户的面再转回去一次。
 */
async function flipTo(nextSlice, commit) {
  pending.value = nextSlice
  await nextTick()
  flipping.value = true
  await wait(reducedMotion ? 0 : FLIP_TOTAL)
  instant.value = true
  commit()
  pending.value = []
  flipping.value = false
  await nextTick()
  requestAnimationFrame(() => requestAnimationFrame(() => { instant.value = false }))
}

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
  if (refreshing.value || flipping.value) return
  exhausted.value = false
  // 这一批还有没看过的：直接翻到后 4 件，不打后端。
  // 改版后同样是"翻牌"——本地换批和后端换批必须长得一样，否则用户以为只有一半能翻。
  if ((page.value + 1) * PAGE_SIZE < products.value.length) {
    const nextPage = page.value + 1
    await flipTo(
      products.value.slice(nextPage * PAGE_SIZE, (nextPage + 1) * PAGE_SIZE),
      () => { page.value = nextPage },
    )
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
      await flipTo((data.products || []).slice(0, PAGE_SIZE), () => { apply(data) })
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
        :disabled="refreshing || flipping"
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
          v-for="(product, index) in visible"
          :key="index"
          class="rec-card"
          :class="{ 'is-flipping': flipping }"
          :title="EMPTY_STATE.cardHint"
        >
          <!-- 扑克牌式翻面：正面是当前这批，背面是待换上来的那批。
               背面平时是空的（pending 为空 → 不渲染内容），所以不会翻出一张白牌。
               key 用 index 而不是 product_id —— 用 id 的话换批时整个 DOM 会被重建，
               翻面动画在中途就被打断了。 -->
          <div
            class="rec-flip"
            :class="{ 'rec-flip-instant': instant }"
            :style="flipStyle(index)"
          >
            <div
              v-for="face in facesFor(index)"
              :key="face.side"
              class="rec-face"
              :class="{ 'rec-face-back': face.side === 'back' }"
            >
              <template v-if="face.product">
                <button
                  class="rec-main"
                  type="button"
                  :disabled="disabled"
                  @click="emit('pick', face.product)"
                >
                  <div class="rec-thumb">
                    <img
                      v-if="face.product.image_url && !brokenImages.has(face.product.product_id)"
                      :src="face.product.image_url"
                      :alt="face.product.title"
                      loading="lazy"
                      @error="brokenImages.add(face.product.product_id)"
                    />
                    <span v-else>暂无图片</span>
                  </div>
                  <div class="rec-body">
                    <h3 class="rec-title">{{ face.product.title }}</h3>
                    <p class="rec-price">
                      {{ priceMain(face.product) }}
                      <span v-if="priceSub(face.product)" class="rec-price-sub">{{ priceSub(face.product) }}</span>
                    </p>
                    <span v-if="reason(face.product)" class="rec-reason">{{ reason(face.product) }}</span>
                  </div>
                </button>
                <button
                  class="fav-btn fav-btn-sm rec-fav"
                  :class="{ 'fav-btn-on': isFavorited(face.product) }"
                  type="button"
                  :disabled="favBusy === face.product.product_id"
                  @click.stop="emit('toggle-favorite', face.product)"
                >
                  {{ isFavorited(face.product) ? '已收藏' : '收藏' }}
                </button>
              </template>
            </div>
          </div>
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
