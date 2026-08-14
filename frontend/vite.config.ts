import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiTarget = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000'
const apiProxy = [
  '/api',
  '/admin',
  '/auth',
  '/orgs',
  '/workspaces',
  '/field-contexts',
  '/geo',
  '/threads',
  '/chat',
  '/route',
  '/retrieve',
  '/tools',
  '/attachments',
  '/messages',
  '/eval-candidates',
  '/eval-runs',
  '/change-proposals',
  '/data-sources',
  '/ingest-jobs',
  '/corpus-health',
  '/quotas',
  '/audit-events',
  '/exports',
  '/export-jobs',
  '/image-rag',
].reduce<Record<string, { target: string; changeOrigin: boolean }>>((proxy, path) => {
  proxy[path] = { target: apiTarget, changeOrigin: true }
  return proxy
}, {})

export default defineConfig({
  plugins: [react()],
  build: {
    // The field client contract requires an ES2020-capable browser. Keeping
    // that target explicit avoids silently transpiling the local/offline
    // bundle back above its measured raw-byte budget.
    target: 'es2020',
  },
  server: {
    proxy: apiProxy,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    // JSDOM test files are isolated; threads avoid the process-spawn overhead
    // of the default fork pool without changing file-level test isolation.
    pool: 'threads',
    poolOptions: {
      threads: {
        minThreads: 6,
        maxThreads: 6,
      },
    },
  },
})
