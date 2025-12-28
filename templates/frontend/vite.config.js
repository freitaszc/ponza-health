import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const isDev = mode === 'development'

  return {
    plugins: [react()],
    base: isDev ? '/' : '/static/react/',
    build: {
      outDir: '../../static/react',
      emptyOutDir: true,
      assetsDir: 'assets',
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        // Only forward image assets to Flask during dev; leave React assets to Vite
        '/static/images': 'http://localhost:5000',
        '/static/uploads': 'http://localhost:5000',
        '/static/profile_images': 'http://localhost:5000',
        '/api': 'http://localhost:5000',
      },
    },
  }
})
