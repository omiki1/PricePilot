// 后端地址：开发时走 vite 代理（同源），也可以用 VITE_API_BASE 直连后端。
const API_BASE = import.meta.env.VITE_API_BASE || ''

/** 健康检查：确认后端、图、收藏表三件东西的装配情况。 */
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
 * 收藏不在这个流里：收藏是商品卡上的按钮，直接调下面的收藏接口，
 * 不走模型、不重新检索，也不在对话里回话。
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

// ---------------------------------------------------------------- 用户账号
// 后端约定：一律返回 { code, msg, data }，HTTP 状态码永远是 200。
// 所以判成败要看 body.code，不能看 response.ok。

function unwrap(body) {
  // code=200 成功，其余都当失败抛出（带后端给的 msg）
  if (body && body.code === 200) return body.data
  const error = new Error((body && body.msg) || '请求失败')
  error.code = body && body.code
  return Promise.reject(error)
}

/** 账号密码登录。account 可以是邮箱或手机号。 */
export async function login({ account, password }) {
  const params = new URLSearchParams({ account, password })
  const response = await fetch(`${API_BASE}/user/login?${params.toString()}`, { method: 'POST' })
  return unwrap(await response.json())
}

/** 注册。姓名 + 邮箱 + 密码 + 手机号。 */
export async function register({ name, email, password, phone }) {
  const response = await fetch(`${API_BASE}/user/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, email, password, phone }),
  })
  return unwrap(await response.json())
}

/** 给已注册邮箱发验证码。 */
export async function sendEmailCode({ email }) {
  const params = new URLSearchParams({ email })
  const response = await fetch(`${API_BASE}/user/sendEmail?${params.toString()}`)
  return unwrap(await response.json())
}

/** 校验邮箱验证码，成功后返回用户信息。 */
export async function verifyCode({ email, code }) {
  const params = new URLSearchParams({ email, code })
  const response = await fetch(`${API_BASE}/user/verifyCode?${params.toString()}`)
  return unwrap(await response.json())
}

/** 把后端错误统一成一句人能看懂的话。 */
async function readError(response) {
  let detail = ''
  try {
    const body = await response.json()
    detail = body?.detail || ''
  } catch (error) {
    detail = ''
  }
  if (!detail) detail = `后端返回 ${response.status}`
  const error = new Error(detail)
  error.status = response.status
  return error
}

/**
 * 收藏商品。商品字段原样回传 —— 这张卡本来就是后端推过来的，不需要模型再理解一遍。
 * 返回 { ok, message, total, item }。
 */
export async function addFavorite({ userId, product }) {
  const response = await fetch(`${API_BASE}/api/favorites`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId || 'default', product }),
  })
  if (!response.ok) throw await readError(response)
  return response.json()
}

/** 取消收藏。返回 { ok, message, total }；本来就没收藏时 ok=false，不算错误。 */
export async function removeFavorite({ userId, productId }) {
  const response = await fetch(`${API_BASE}/api/favorites`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId || 'default', product_id: productId }),
  })
  if (!response.ok) throw await readError(response)
  return response.json()
}

/**
 * 某个商品的价格记录。点「价格记录」时才调，不在收藏列表里预加载。
 * 返回 { product_id, points: [{price, recorded_at}] }，points 按时间正序。
 * 只给数据不算涨跌：样本太少时那种结论本身就是误导。
 */
export async function fetchPriceHistory({ productId, limit = 60 }) {
  const params = new URLSearchParams({ product_id: productId, limit: String(limit) })
  const response = await fetch(`${API_BASE}/api/products/price-history?${params.toString()}`)
  if (!response.ok) throw await readError(response)
  return response.json()
}

/** 拉收藏夹。返回 { user_id, total, favorites: [...] }。 */
export async function fetchFavorites({ userId, limit = 100 } = {}) {
  const params = new URLSearchParams({
    user_id: userId || 'default',
    limit: String(limit),
  })
  const response = await fetch(`${API_BASE}/api/favorites?${params.toString()}`)
  if (!response.ok) throw await readError(response)
  return response.json()
}
