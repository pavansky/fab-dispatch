// Shared setup for component tests (Vitest + jsdom + Testing Library).
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'
import { clearPlanCache, setTokenProvider } from '../api.js'

// jsdom has no layout engine: provide the browser APIs the UI reads.
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: query.includes('min-width'), media: query, onchange: null,
    addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false,
  })
}

afterEach(() => {
  cleanup()
  clearPlanCache()
  setTokenProvider(() => null)
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
  history.replaceState(null, '', '/')
})
