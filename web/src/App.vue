<script setup>
import { computed, onMounted, ref } from 'vue'
import { fetchHealth, parseIntent, recognizeIntent } from './api.js'

const question = ref('我想买一个1000以内的无线耳机')
const userId = ref('u001')
const sessionId = ref('s001')

const loading = ref(false)
const error = ref('')
const result = ref(null)
const health = ref(null)

const samples = [
  '我想买一个1000以内的无线耳机',
  '推荐个500块左右的机械键盘',
  '一千到两千的显示器',
  '你好呀',
]

const summary = computed(() => (result.value ? parseIntent(result.value.text) : null))

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
  } catch (exception) {
    error.value = exception.message || '请求失败'
  } finally {
    loading.value = false
  }
}

function useSample(sample) {
  question.value = sample
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
      <h1>PricePilot · 意图识别</h1>
      <p class="subtitle">当前页面只接入已完成的意图识别节点（START → intent → END）。</p>
      <span class="badge" :class="health && health.status === 'ok' ? 'badge-ok' : 'badge-bad'">
        后端：{{ health ? health.status : '检测中' }}
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
        <button v-for="sample in samples" :key="sample" type="button" class="chip" @click="useSample(sample)">
          {{ sample }}
        </button>
      </div>

      <button class="primary" type="button" :disabled="loading" @click="onRecognize">
        {{ loading ? '识别中…' : '开始识别' }}
      </button>
    </section>

    <p v-if="error" class="error">{{ error }}</p>

    <section v-if="result" class="card result">
      <h2>识别结果</h2>
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
  </main>
</template>
