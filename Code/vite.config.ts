import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const dPort = Number(env.PORT || 3001)

  return {
    plugins: [react()],
    server: {
      host: env.VITE_HOST || '127.0.0.1',
      port: Number(env.VITE_PORT || 5173),
      strictPort: true,
      proxy: {
        '/api': {
          target: env.VITE_API_PROXY_TARGET || `http://127.0.0.1:${dPort}`,
          changeOrigin: true,
          // Keep the proxy finite so a dead A端 cannot leave the browser spinning forever.
          timeout: 480000,
          proxyTimeout: 480000,
        },
      },
    },
  }
})
