// PricePilot 首页推荐与会话管理的界面文案（写手Bot 2026-09-29，说明见 PricePilot_界面文案.md）
export const EMPTY_STATE = {
  title: '想买点什么？',
  subtitle: '说清商品和预算，我来帮你找。',
  recTitle: { profile: '按你的偏好挑了几件', favorites: '和你收藏的差不多', none: '不知道从哪开始？试试这样问' },
  refresh: '换一批',
  refreshing: '正在换…',
  refreshExhausted: '暂时只有这些，聊几句我能推得更准',
  cardHint: '根据你的购物偏好推荐，偏好会随聊天自动更新',
  sampleQuestions: [
    '500 以内的无线机械键盘',
    '适合通勤的降噪耳机，预算 1000',
    '给爸妈买的血压计，要大屏的',
    '200 左右的保温杯，别太重',
  ],
}

const clip = (s, n = 6) => (s && s.length > n ? s.slice(0, n) + '…' : s || '')

/**
 * 推荐理由，一般不超过 16 字。match 由后端给出：
 * { category?: string, brand?: string, inBudget?: boolean, favoriteName?: string }
 * 只用命中的字段拼，不喜欢的品牌不进文案。
 */
export function recReason(match = {}) {
  const c = clip(match.category), b = clip(match.brand)
  if (c && b) return `你常买${c} · 偏好${b}`
  if (b) return `你偏好的${b}`
  if (c && match.inBudget) return `你常买${c} · 在预算内`
  if (c) return `你常买${c}`
  if (match.inBudget) return '在你常用的预算内'
  if (match.favoriteName) return `和你收藏的${clip(match.favoriteName, 8)}同类`
  return ''
}

export const SIDEBAR = {
  newChat: '新建对话',
  groups: { today: '今天', yesterday: '昨天', week: '7 天内', earlier: '更早' },
  untitled: '新对话',
  rename: '重命名',
  delete: '删除',
  renamePlaceholder: '给这段对话起个名字',
  renameEmpty: '名字不能为空',
  deleteTitle: '删除这段对话？',
  deleteBody: '聊天记录和里面的商品卡都会删掉，收藏夹不受影响。',
  confirmDelete: '删除',
  cancel: '取消',
  deleted: '已删除',
  empty: '还没有历史对话。聊过的内容会保存在这里。',
  loading: '正在读取…',
  collapse: '收起侧栏',
  expand: '展开侧栏',
}

/** 第一句提问作标题：去换行和首尾空格，最多 20 字 */
export function autoTitle(question) {
  const t = (question || '').replace(/\s+/g, ' ').trim()
  if (!t) return SIDEBAR.untitled
  return t.length > 20 ? t.slice(0, 20) + '…' : t
}

export const ERRORS = {
  recFailed: '推荐暂时加载不出来，直接告诉我想买什么也行。',
  listFailed: '历史对话加载失败',
  retry: '重试',
  openFailed: '这段对话打不开了，可能已被删除。',
  forbidden: '这段对话不属于当前账号。',
  actionFailed: '操作失败，稍后再试',
  streamBroken: '连接断了，这一轮没说完。可以再发一次。',
  saveFailed: '这轮回答没存进历史，刷新后会看不到。',
  loginRequired: '登录后才能保存和查看历史对话',
}

export const FAVORITES = { drawerClose: '关闭收藏夹' }

/** 点首页推荐卡：拼成整句填进输入框（不自动发送，用户可以改）。商品名超过 30 字截断。 */
export function cardQuestion(title) {
  const t = (title || '').replace(/\s+/g, ' ').trim()
  if (!t) return ''
  const name = t.length > 30 ? t.slice(0, 30) + '…' : t
  return `帮我看看「${name}」值不值得买，有没有更合适的同类`
}
