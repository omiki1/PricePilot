import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 前后端分离：前端固定跑 8080，后端跑 8000（和 app/main.py 的 uvicorn port 保持一致）。
//
// 原注释写的是后端用 8081，理由是"8000 落在 Windows 给 Hyper-V/WSL 的保留段"。
// 但本机实测：8000 能正常绑定（后端就跑在上面），8081 反而没人监听，
// 结果四条代理全部 ECONNREFUSED、页面发出去没有任何回应。所以对齐到 8000。
//
// 改 main.py 的端口时，记得同步改这里 —— 两处对不上就会静默连不上。
//
// 所有代理必须指向同一个后端：之前 /chat 指 8000、/api 和 /health 指 8081，
// 结果聊天永远连不上，页面表现就是"发出去没有任何回应"。
//
// 加了后端新路由（比如 /user/*）记得同步加一条代理 ——
// 漏了不会报"没配代理"，而是被 vite 当成前端路由返回 index.html，
// 前端拿到的是 HTML、JSON.parse 直接炸，很难一眼看出是代理问题。
const BACKEND = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 8080,
    strictPort: true,
    // 排除 node_modules 与构建产物：只监听 src 下的文件，
    // 既省资源，也避免编辑器/工具往目录里写临时文件时 watcher 报 EBUSY 直接把 dev server 打挂
    // （Windows 上写过一次：watch '.App.vue.xxx.tmpdir/App.vue.tmp' → EBUSY，进程直接退出）
    watch: {
      // 注意：ignored 对 chokidar 是**前缀匹配**，写成 '**/src/**' 会把 src 自己也忽略掉，
      // src 一改页面就不热更新。要按扩展名忽略临时文件就得写 '**/*.tmpdir/**' 这种。
      //
      // 这里只忽略 src 目录树内的临时残留（编辑器/文件工具写入时留下的 .xxx.tmpdir），
      // 它们是 EBUSY 的来源：watch 一个正在被写的临时文件会让 dev server 直接退出
      // （Windows 实测踩过两次）。
      ignored: [
        '**/node_modules/**',
        '**/dist/**',
        '**/.git/**',
        // 临时目录可能出现在任何层级：src/ 下（改 App.vue 时）和 web/ 根下（改本文件时）
        // 都踩过 EBUSY，所以不限定目录，按名字忽略
        '**/.*.tmpdir/**',
        '**/*.tmpdir/**',
      ],
    },
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
      },
      // 聊天 SSE 接口：不代理的话 /chat 会被 vite 当成前端路由返回 index.html，
      // EventSource 拿到 HTML 解析不出帧，页面表现就是"没有任何回应"
      '/chat': {
        target: BACKEND,
        changeOrigin: true,
        // SSE 必须关闭压缩与缓冲，否则消息会被攒着不下发
        headers: { 'Accept-Encoding': 'identity' },
      },
      '/health': {
        target: BACKEND,
        changeOrigin: true,
      },
      // 用户账号：/user/login、/user/register、/user/sendEmail、/user/verifyCode
      '/user': {
        target: BACKEND,
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 8080,
  },
})
