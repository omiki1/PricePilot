// 后端地址：开发时走 vite 代理（同源），也可以用 VITE_API_BASE 直连后端。
const API_BASE = import.meta.env.VITE_API_BASE || ''

/** 健康检查：确认后端与图是否装配完成。 */
export async function fetchHealth() {
  const response = await fetch(`${API_BASE}/health`)
  if (!response.ok) {
    throw new Error(`后端返回 ${response.status}`)
  }
  return response.json()
}

/**
 * 聊天：GET /chat?question=...&user_id=...&session_id=... （SSE 流式）
 *
 * 后端按顺序推三种帧：
 *   {type: 'text',     data: '增量文本'}
 *   {type: 'products', data: [Product...]}   ← 图状态里的检索结果
 *   {done: true}                             ← 结束
 *
 * 用 EventSource（浏览器原生，自动处理分帧）。
 */
export function openChat({ question, userId, sessionId, onText, onProducts, onDone, onError }) {
  const params = new URLSearchParams({
    question,
    user_id: userId || 'default',
    session_id: sessionId || '',
  })
  const source = new EventSource(`${API_BASE}/chat?${params.toString()}`)

  source.onmessage = (event) => {
    let payload = null
    try {
      payload = JSON.parse(event.data)
    } catch (error) {
      return
    }

    if (payload.done) {
      source.close()
      if (payload.data && onError) onError(payload.data)
      if (onDone) onDone()
      return
    }
    if (payload.type === 'text' && onText) {
      onText(payload.data ?? '')
    } else if (payload.type === 'products' && onProducts) {
      onProducts(payload.data ?? [])
    }
  }

  source.onerror = () => {
    // 连接关闭或出错：结束本轮；EventSource 的自动重连不需要（每轮都是新连接）
    source.close()
    if (onDone) onDone()
  }

  return source
}
