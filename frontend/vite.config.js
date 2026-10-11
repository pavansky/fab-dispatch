import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Same Content-Security-Policy as production (vercel.json), so `npm run preview` tests the
// built app under the real policy.
const CSP = "default-src 'self'; script-src 'self' https://challenges.cloudflare.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self' https://*.supabase.co wss://*.supabase.co; frame-src https://challenges.cloudflare.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"

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
    // GitHub Codespaces serves the forwarded port on *.app.github.dev.
    allowedHosts: ['.app.github.dev'],
  },
  // Unit and component tests (Vitest, jsdom). Browser end-to-end tests live in e2e/ (Playwright).
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    // Rendering the whole app with the real fixtures takes a few seconds on a loaded runner; the
    // 5 s default made two app-level tests flaky under CI contention without any code change.
    testTimeout: 15_000,
    include: ['src/**/*.test.{js,jsx}'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{js,jsx}'],
      exclude: ['src/test/**', 'src/**/*.test.{js,jsx}', 'src/main.jsx'],
      reporter: ['text-summary', 'text'],
      // Floors, not targets: one point below the last measured run (lines 95.5%, statements
      // 92.1%, functions 89.7%, branches 82.1%), so CI fails on a real drop and nobody has to
      // chase a number. Raise them when a run measures higher.
      thresholds: { lines: 94, statements: 91, functions: 88, branches: 81 },
    },
  },
})
