import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'fs'
import { resolve } from 'path'

function readEnvToken(): string {
  try {
    const content = readFileSync(resolve(process.cwd(), '.env'), 'utf-8')
    const match = content.match(/^JELLYFISH_INTERNAL_TOKEN=(.+)$/m)
    return match?.[1]?.trim() || 'dev-internal-token'
  } catch {
    return 'dev-internal-token'
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const internalToken = env.JELLYFISH_INTERNAL_TOKEN || readEnvToken()

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
