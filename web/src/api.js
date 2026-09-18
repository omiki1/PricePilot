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
