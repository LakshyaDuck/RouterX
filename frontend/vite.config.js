import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backendTarget = process.env.BACKEND_URL || 'http://127.0.0.1:8000'
const port = parseInt(process.env.PORT || '5173', 10)

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
      },
      '/simulation': {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
})

