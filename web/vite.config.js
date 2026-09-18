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
