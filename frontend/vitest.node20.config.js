// The subset of the suite that Node 20 can run. jsdom 30 (the component-test environment)
// requires Node 22, so on the oldest Node the app supports CI runs the build, the lint and the
// pure-library tests here; the full suite runs on Node 22. See the frontend-node20 job in ci.yml.
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/lib/__tests__/*.test.js'],
  },
})
