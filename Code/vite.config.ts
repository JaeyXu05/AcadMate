import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:3001',
        changeOrigin: true,
        // Keep the proxy finite so a dead A端 cannot leave the browser spinning forever.
        timeout: 480000,
        proxyTimeout: 480000,
      },
    },
  },
})
