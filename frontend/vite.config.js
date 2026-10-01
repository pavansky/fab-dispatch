import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Same Content-Security-Policy as production (vercel.json), so `npm run preview` tests the
// built app under the real policy.
const CSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self' https://*.supabase.co wss://*.supabase.co; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"

export default defineConfig({
  plugins: [react()],
  preview: {
    port: 4173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
    headers: { 'Content-Security-Policy': CSP },
  },
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  // Unit and component tests (Vitest, jsdom). Browser end-to-end tests live in e2e/ (Playwright).
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    include: ['src/**/*.test.{js,jsx}'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{js,jsx}'],
      exclude: ['src/test/**', 'src/**/*.test.{js,jsx}', 'src/main.jsx'],
      reporter: ['text-summary', 'text'],
      // Floors, not targets: CI fails if coverage drops below today's level.
      thresholds: { lines: 85, statements: 80, functions: 75, branches: 70 },
    },
  },
})
