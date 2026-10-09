import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const internalToken = env.JELLYFISH_INTERNAL_TOKEN || 'dev-internal-token'

  return {
    plugins: [react()],
    appType: 'spa',
    server: {
      port: 7788,
      open: true,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:9123',
          changeOrigin: true,
          configure: (proxy) => {
            proxy.on('proxyReq', (proxyReq) => {
              proxyReq.setHeader('X-Internal-Token', internalToken)
            })
          },
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
    },
  }
})
