import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 前后端分离：前端固定跑 8080，后端跑 8000。
// 直连时走 CORS；也可把 VITE_API_BASE 留空，走 dev 代理（同源 /api）。
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 8080,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // 聊天 SSE 接口：不代理的话 /chat 会被 vite 当成前端路由返回 index.html，
      // EventSource 拿到 HTML 解析不出帧，页面表现就是"没有任何回应"
      '/chat': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // SSE 必须关闭压缩与缓冲，否则消息会被攒着不下发
        headers: { 'Accept-Encoding': 'identity' },
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 8080,
  },
})
