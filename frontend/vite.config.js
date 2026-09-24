import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    Components({ resolvers: [ElementPlusResolver()], dts: false }),
  ],
  server: {
    port: 5173,
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
