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
})
