// 把模型输出的 Markdown 渲染成安全的 HTML。
//
// 为什么渲染后一定要过 DOMPurify：
// 正文有两处不可信来源——大模型自己生成的内容，以及 recommend 节点从百度千帆
// 搜回来的第三方网页摘要。这些字符串会经 v-html 直接插进 DOM，不过消毒就有 XSS 风险。
// marked 只负责把 Markdown 转成 HTML，不做任何安全过滤，两者必须配对使用。
import { marked } from 'marked'
import DOMPurify from 'dompurify'

// 允许的标签：常规 Markdown 结构 + 表格（推荐结果里常有对比表格）。
// 白名单式放行，比默认更严格，避免模型顺手吐个 iframe/script 进来。
const ALLOWED_TAGS = [
  'p', 'br', 'hr', 'span',
  'strong', 'em', 'del', 'sup', 'sub',
  'code', 'pre', 'blockquote',
  'ul', 'ol', 'li',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'a', 'img',
  'table', 'thead', 'tbody', 'tr', 'th', 'td',
]

const ALLOWED_ATTR = ['href', 'title', 'src', 'alt', 'class', 'align']

// 正文里的链接一律新窗口打开，并切断 referrer / opener，避免把当前页带跑。
// 用 hook 而不是 ALLOWED_ATTR 加 target：属性白名单只管"能不能留"，
// 管不了"强制补上"，而目标页的 _blank 行为需要由我们统一决定。
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A' && node.getAttribute('href')) {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

/**
 * Markdown 文本 → 已消毒的 HTML 字符串。
 *
 * 流式场景下会被高频调用，且入参经常是"半截"的 Markdown（例如 `**加粗` 还没闭合），
 * 这里不做特殊兜底：marked 对未闭合语法会原样输出，视觉上就是先显示字面量、
 * 补全后再变样式，这正是流式该有的表现。
 *
 * @param {string} text 模型输出的原始文本
 * @returns {string} 可直接交给 v-html 的 HTML
 */
export function renderMarkdown(text) {
  if (!text) return ''

  // 选项在这里传而不是 marked.setOptions：按调用传参不受 marked 版本间
  // 全局配置 API 变动的影响。
  const html = marked.parse(String(text), {
    gfm: true,
    // 模型输出常靠单个换行分段，GitHub 风格的 breaks 更贴合预期
    breaks: true,
  })

  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    // 不放行 data-* / aria-*，模型生成的内容不需要这些
    ALLOW_DATA_ATTR: false,
    // 图片只认 http(s)，挡掉 data: / javascript: 之类的协议
    ALLOWED_URI_REGEXP: /^(?:https?|mailto):/i,
  })
}
