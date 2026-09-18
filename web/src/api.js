// 后端地址：开发时走 vite 代理（同源 /api），也可以用 VITE_API_BASE 直连后端。
const API_BASE = import.meta.env.VITE_API_BASE || ''

/** 健康检查：确认后端与图是否装配完成。 */
export async function fetchHealth() {
  const response = await fetch(`${API_BASE}/health`)
  if (!response.ok) {
    throw new Error(`后端返回 ${response.status}`)
  }
  return response.json()
}

/** 意图识别：只调用当前已完成的意图识别接口 POST /api/intent。 */
export async function recognizeIntent({ question, userId, sessionId }) {
  const response = await fetch(`${API_BASE}/api/intent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      user_id: userId || 'default',
      session_id: sessionId || '',
    }),
  })

  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = payload && payload.detail ? payload.detail : `请求失败（${response.status}）`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return payload
}

/** 从后端返回的一句话里取出 category / price，仅用于展示，不参与业务判断。 */
export function parseIntent(text) {
  const categoryMatch = text.match(/商品类型[：:]\s*([^\s，,。]*)/)
  const priceMatch = text.match(/价格在[：:]\s*([\d.]+)/)
  const category = categoryMatch ? categoryMatch[1] : ''
  const price = priceMatch ? priceMatch[1] : ''
  return {
    category: category || '未提到商品',
    price: price ? String(Number(price)) : '未提到价格',
  }
}

/**
 * 列出当前启用的来源（含计费说明与缓存状态）：GET /api/sources。
 * 前端据此渲染来源标签，不写死来源名。
 */
export async function fetchSources() {
  const response = await fetch(`${API_BASE}/api/sources`)
  if (!response.ok) {
    throw new Error(`后端返回 ${response.status}`)
  }
  return response.json()
}

/**
 * 多来源商品检索：POST /api/products/search。
 * 每个来源各自返回状态（completed / needs_session / failed / timeout…），
 * 一个来源失败不影响另一个，所以结果要按 outcome.status 如实展示。
 */
export async function searchProducts({ keyword, sources = [], limit = 6 }) {
  const response = await fetch(`${API_BASE}/api/products/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keyword, sources, limit }),
  })

  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = payload && payload.detail ? payload.detail : `请求失败（${response.status}）`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return payload
}

/**
 * 闲鱼商品检索（旧接口，保留兼容）：POST /api/xianyu/search。
 * mode='feed' 匿名可用（拿到的是推荐流，与关键词无关）；
 * mode='search' 需要闲鱼登录态，没有时会返回 status='needs_session'，属于正常结果不是报错。
 */
export async function searchXianyu({ keyword, mode = 'feed', limit = 12 }) {
  const response = await fetch(`${API_BASE}/api/xianyu/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keyword, mode, limit }),
  })

  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = payload && payload.detail ? payload.detail : `请求失败（${response.status}）`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return payload
}
