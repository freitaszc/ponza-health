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
        // Forward Flask-managed pages/assets during dev
        '/static': 'http://localhost:5000',
        '/api': 'http://localhost:5000',
        '/download_pdf': 'http://localhost:5000',
        '/lab_analysis/pdf': 'http://localhost:5000',
        '/public_download': 'http://localhost:5000',
        '/products/': 'http://localhost:5000',
        '/delete_product': 'http://localhost:5000',
        '/toggle_patient_status': 'http://localhost:5000',
        '/delete_patient': 'http://localhost:5000',
        '/suppliers/': 'http://localhost:5000',
        '/update_supplier': 'http://localhost:5000',
        '/purchase_package': 'http://localhost:5000',
        '/subscribe_pay': 'http://localhost:5000',
        '/doctors': 'http://localhost:5000',
        '/doctor_view': 'http://localhost:5000',
        '/logout': 'http://localhost:5000',
      },
    },
  }
})
