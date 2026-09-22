<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { login, register, sendEmailCode, verifyCode } from './api.js'

const emit = defineEmits(['logged-in'])

// 三个页签：密码登录 / 验证码登录 / 注册
const tab = ref('password')
const busy = ref(false)
const notice = ref('')
const noticeType = ref('error')       // error | ok

const form = reactive({
  account: '',
  password: '',
  email: '',
  code: '',
  name: '',
  regEmail: '',
  regPassword: '',
  regPhone: '',
})

// 验证码倒计时：后端 Redis 里 60 秒过期，这里跟着倒
const countdown = ref(0)
let timer = null

function say(text, type = 'error') {
  notice.value = text
  noticeType.value = type
}

function clearNotice() {
  notice.value = ''
}

function startCountdown() {
  countdown.value = 60
  clearInterval(timer)
  timer = setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) clearInterval(timer)
  }, 1000)
}

onMounted(() => clearInterval(timer))

// ---- 密码登录 ----
async function onPasswordLogin() {
  if (!form.account.trim() || !form.password) {
    say('账号和密码都要填')
    return
  }
  busy.value = true
  clearNotice()
  try {
    const user = await login({ account: form.account.trim(), password: form.password })
    say('登录成功，' + (user?.username || ''), 'ok')
    emit('logged-in', user)
  } catch (exception) {
    say(exception.message)
  } finally {
    busy.value = false
  }
}

// ---- 验证码 ----
async function onSendCode() {
  const email = form.email.trim()
  if (!email) {
    say('先填邮箱')
    return
  }
  busy.value = true
  clearNotice()
  try {
    await sendEmailCode({ email })
    say('验证码已发送，60 秒内有效', 'ok')
    startCountdown()
  } catch (exception) {
    say(exception.message)
  } finally {
    busy.value = false
  }
}

async function onCodeLogin() {
  if (!form.email.trim() || !form.code.trim()) {
    say('邮箱和验证码都要填')
    return
  }
  busy.value = true
  clearNotice()
  try {
    const user = await verifyCode({ email: form.email.trim(), code: form.code.trim() })
    say('登录成功，' + (user?.username || ''), 'ok')
    emit('logged-in', user)
  } catch (exception) {
    say(exception.message)
  } finally {
    busy.value = false
  }
}

// ---- 注册 ----
// 前端先做一遍格式检查，省一次往返；后端还会再校验一次，这里不是唯一防线
const EMAIL_RE = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/
const PHONE_RE = /^1[3-9]\d{9}$/
const PASSWORD_RE = /^[A-Za-z0-9]{8,16}$/

const registerHint = computed(() => {
  const tips = []
  if (form.regEmail && !EMAIL_RE.test(form.regEmail)) tips.push('邮箱格式不对')
  if (form.regPhone && !PHONE_RE.test(form.regPhone)) tips.push('手机号要是 11 位数字')
  if (form.regPassword && !PASSWORD_RE.test(form.regPassword)) tips.push('密码 8~16 位字母数字')
  return tips.join('，')
})

async function onRegister() {
  const name = form.name.trim()
  const email = form.regEmail.trim()
  const phone = form.regPhone.trim()

  if (!name || !email || !form.regPassword || !phone) {
    say('姓名、邮箱、密码、手机号都要填')
    return
  }
  if (!EMAIL_RE.test(email) || !PHONE_RE.test(phone) || !PASSWORD_RE.test(form.regPassword)) {
    say(registerHint.value || '格式不对')
    return
  }

  busy.value = true
  clearNotice()
  try {
    await register({ name, email, password: form.regPassword, phone })
    say('注册成功，用这个账号登录吧', 'ok')
    // 注册完直接把账号填进登录框，省得用户再敲一遍
    form.account = email
    form.password = ''
    tab.value = 'password'
  } catch (exception) {
    say(exception.message)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <header class="login-head">
        <h1>PricePilot</h1>
        <p>登录后收藏和价格记录才会跟着你的账号走</p>
      </header>

      <nav class="login-tabs">
        <button type="button" :class="{ on: tab === 'password' }" @click="tab = 'password'; clearNotice()">密码登录</button>
        <button type="button" :class="{ on: tab === 'code' }" @click="tab = 'code'; clearNotice()">验证码登录</button>
        <button type="button" :class="{ on: tab === 'register' }" @click="tab = 'register'; clearNotice()">注册</button>
      </nav>

      <!-- 密码登录：账号可以是邮箱或手机号 -->
      <form v-if="tab === 'password'" class="login-form" @submit.prevent="onPasswordLogin">
        <label class="login-field">
          <span>账号</span>
          <input v-model="form.account" type="text" placeholder="邮箱或手机号" autocomplete="username" />
        </label>
        <label class="login-field">
          <span>密码</span>
          <input v-model="form.password" type="password" placeholder="密码" autocomplete="current-password" />
        </label>
        <button class="login-submit" type="submit" :disabled="busy">
          {{ busy ? '登录中…' : '登录' }}
        </button>
      </form>

      <!-- 验证码登录 -->
      <form v-else-if="tab === 'code'" class="login-form" @submit.prevent="onCodeLogin">
        <label class="login-field">
          <span>邮箱</span>
          <input v-model="form.email" type="email" placeholder="已注册的邮箱" />
        </label>
        <label class="login-field">
          <span>验证码</span>
          <div class="login-code">
            <input v-model="form.code" type="text" maxlength="8" placeholder="6 位数字" />
            <button type="button" :disabled="busy || countdown > 0" @click="onSendCode">
              {{ countdown > 0 ? countdown + 's' : '发送验证码' }}
            </button>
          </div>
        </label>
        <button class="login-submit" type="submit" :disabled="busy">
          {{ busy ? '验证中…' : '登录' }}
        </button>
      </form>

      <!-- 注册 -->
      <form v-else class="login-form" @submit.prevent="onRegister">
        <label class="login-field">
          <span>姓名</span>
          <input v-model="form.name" type="text" placeholder="用户名" />
        </label>
        <label class="login-field">
          <span>邮箱</span>
          <input v-model="form.regEmail" type="email" placeholder="name@example.com" />
        </label>
        <label class="login-field">
          <span>密码</span>
          <input v-model="form.regPassword" type="password" placeholder="8~16 位字母数字" autocomplete="new-password" />
        </label>
        <label class="login-field">
          <span>手机号</span>
          <input v-model="form.regPhone" type="text" maxlength="11" placeholder="11 位手机号" />
        </label>
        <p v-if="registerHint" class="login-hint">{{ registerHint }}</p>
        <button class="login-submit" type="submit" :disabled="busy">
          {{ busy ? '提交中…' : '注册' }}
        </button>
      </form>

      <p v-if="notice" class="login-notice" :class="noticeType === 'ok' ? 'login-notice-ok' : 'login-notice-err'">
        {{ notice }}
      </p>
    </div>
  </div>
</template>
