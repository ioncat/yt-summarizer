import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig(({ mode }) => {
  // Always resolve .env from project root (two levels up from app/frontend/)
  const env = loadEnv(mode, path.resolve(__dirname, '../..'), '')
  const frontendPort = parseInt(process.env.PORT ?? env.FRONTEND_PORT ?? '3000')
  const backendPort = env.BACKEND_PORT ?? '8000'

  return {
    plugins: [tailwindcss(), react()],
    server: {
      port: frontendPort,
      proxy: {
        '/api': `http://localhost:${backendPort}`,
      },
    },
  }
})
