import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/query': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/build': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/datasets': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
