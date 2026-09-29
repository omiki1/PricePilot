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

// 右栏标题跟着页签走：切页签时先说清"这一步在做什么"，比一个固定的"登录"清楚
const PANELS = {
  password: { title: '密码登录', sub: '用注册时的邮箱或手机号登录' },
  code: { title: '验证码登录', sub: '验证码发到已注册邮箱，60 秒内有效' },
  register: { title: '创建账号', sub: '注册后收藏与价格记录会跟着账号走' },
}
const panel = computed(() => PANELS[tab.value] || PANELS.password)

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
// 手机号只校验"11 位数字"，不再限制号段。
// 用 [0-9] 而不是 \d，和后端 UserService.PATTERN_PHONE 保持同一套语义。
const PHONE_RE = /^[0-9]{11}$/
const PASSWORD_RE = /^[A-Za-z0-9]{8,16}$/

/**
 * 手机号归一化：全角数字转半角 + 去掉空格/连字符/括号。
 *
 * 中文输入法直接敲出来的数字是全角的，粘贴过来的手机号又常带分隔符。
 * 不归一化就会被判成"位数不对" —— 用户数着明明是 11 位，提示却说不够 11 位。
 */
function normalizePhone(value) {
  return String(value || '')
    .replace(/[０-９]/g, (ch) => String.fromCharCode(ch.charCodeAt(0) - 0xfee0))
    .replace(/[\s\-()（）]/g, '')
}

// 输入框里存原始字符串，校验和提交都走归一化后的值
const normalizedPhone = computed(() => normalizePhone(form.regPhone))

const registerHint = computed(() => {
  const tips = []
  if (form.regEmail && !EMAIL_RE.test(form.regEmail)) tips.push('邮箱格式不对')
  if (form.regPhone && !PHONE_RE.test(normalizedPhone.value)) tips.push('手机号要是 11 位数字')
  if (form.regPassword && !PASSWORD_RE.test(form.regPassword)) tips.push('密码 8~16 位字母数字')
  return tips.join('，')
})

async function onRegister() {
  const name = form.name.trim()
  const email = form.regEmail.trim()
  // 提交归一化后的手机号：后端存的、以后登录时比对的都是它
  const phone = normalizedPhone.value

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
    <!-- ── 左：品牌墙。黑底 + 极光蓝光晕 + 右下角一枚巨大斜杠 ── -->
    <section class="login-hero">
      <div class="login-hero-top">
        <span class="login-hero-brand">PricePilot</span>
      </div>

      <div class="login-hero-main">
        <p class="login-hero-kicker">到手价鉴别所</p>
        <h1 class="login-hero-title">
          标价谁都会写<br />
          <em>到手价才作数</em>
        </h1>
        <p class="login-hero-sub">
          同一件东西，各家平台的标价、运费、优惠券和返现凑在一起，能差出好几百。
          PricePilot 把每一项摊开算清，再告诉你到底要付多少。
        </p>

        <ul class="login-points">
          <li><b>01</b>逐条核验券的资格与可叠加性，算不出来就直说算不出来</li>
          <li><b>02</b>付款金额与预计净成本分两栏，返现不糊进总价</li>
          <li><b>03</b>每条结论都能展开看第三方证据来源</li>
        </ul>
      </div>

      <p class="login-hero-foot">
        登录后收藏与价格记录会跟着账号走 · 本机演示环境，数据以页面标注的来源为准
      </p>
    </section>

    <!-- ── 右：表单 ── -->
    <section class="login-panel">
      <div class="login-card">
        <header class="login-head">
          <h2 class="login-head-title">{{ panel.title }}</h2>
          <p>{{ panel.sub }}</p>
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
            <input v-model="form.email" type="email" placeholder="已注册的邮箱" autocomplete="email" />
          </label>
          <label class="login-field">
            <span>验证码</span>
            <div class="login-code">
              <input v-model="form.code" type="text" maxlength="8" placeholder="6 位数字" inputmode="numeric" autocomplete="one-time-code" />
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
            <input v-model="form.name" type="text" placeholder="用户名" autocomplete="name" />
          </label>
          <label class="login-field">
            <span>邮箱</span>
            <input v-model="form.regEmail" type="email" placeholder="name@example.com" autocomplete="email" />
          </label>
          <label class="login-field">
            <span>密码</span>
            <input v-model="form.regPassword" type="password" placeholder="8~16 位字母数字" autocomplete="new-password" />
          </label>
          <label class="login-field">
            <span>手机号</span>
            <!-- maxlength 放宽到 16：给空格/连字符留位置。若仍是 11，粘贴
                 "138 1234 5678" 会被浏览器先截成 11 个字符，归一化后只剩 9 位数字 -->
            <input
              v-model="form.regPhone"
              type="text"
              maxlength="16"
              placeholder="11 位手机号"
              inputmode="numeric"
              autocomplete="tel"
              @blur="form.regPhone = normalizedPhone"
            />
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
    </section>
  </div>
</template>
