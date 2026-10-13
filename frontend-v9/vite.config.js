import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// V9 前端（frontend-v9）：与旧 frontend/ 并存，端口 5174 避让旧前端 5173；
// 依赖版本与 frontend/package.json 逐字一致（见 docs/FRONTEND_V9_CONTRACTS.md 头注）。
export default defineConfig({
  plugins: [
    vue(),
    Components({ resolvers: [ElementPlusResolver()], dts: false }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5174,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 500,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('zrender')) return 'vendor-renderer'
          if (id.includes('echarts')) return 'vendor-charts'
          if (id.includes('element-plus') || id.includes('@element-plus')) {
            const component = id.match(/element-plus[\\/]es[\\/]components[\\/]([^\\/]+)/)?.[1]
            return component ? `vendor-element-${component}` : 'vendor-element-core'
          }
          if (id.includes('@vue') || id.includes('vue-router') || /node_modules[\\/]vue[\\/]/.test(id)) return 'vendor-vue'
          if (id.includes('axios')) return 'vendor-http'
          return 'vendor-misc'
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.js'],
    clearMocks: true,
  },
})
