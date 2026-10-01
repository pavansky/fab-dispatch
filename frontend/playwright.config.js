// End-to-end tests: the real FastAPI backend and the Vite UI, driven in Chromium.
// Run with `npm run test:e2e` (both servers start automatically). Set E2E_PYTHON to the
// Python that has the backend installed; it defaults to backend/.venv.
import { defineConfig, devices } from '@playwright/test'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const venv = resolve('../backend/.venv/bin/python')
const python = process.env.E2E_PYTHON ?? (existsSync(venv) ? venv : 'python3')
const db = join(tmpdir(), `fab-dispatch-e2e-${process.pid}.db`)

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1, // one backend, shared live-shift state: keep runs deterministic
  retries: process.env.CI ? 1 : 0,
  forbidOnly: Boolean(process.env.CI),
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } }, testIgnore: /mobile\.spec/ },
    { name: 'mobile', use: { ...devices['Pixel 7'] }, testMatch: /mobile\.spec/ },
  ],
  webServer: [
    {
      command: `"${python}" -m uvicorn app.main:app --port 8000`,
      cwd: '../backend',
      url: 'http://127.0.0.1:8000/api/livez',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        FAB_AUTH_MODE: 'demo',
        FAB_DATABASE_URL: `sqlite:///${db}`,
        FAB_ALNS_ITERATIONS: '100',
        FAB_PYVRP_ITERATIONS: '300',
        FAB_LOG_LEVEL: 'WARNING',
      },
    },
    {
      command: 'npm run dev -- --port 5173 --strictPort',
      url: 'http://localhost:5173',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
})
