import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const frontendPort = parseInt(env.FRONTEND_PORT ?? '3000')
  const backendPort = env.BACKEND_PORT ?? '8000'

  return {
    plugins: [react()],
    server: {
      port: frontendPort,
      proxy: {
        '/api': `http://localhost:${backendPort}`,
      },
    },
  }
})
