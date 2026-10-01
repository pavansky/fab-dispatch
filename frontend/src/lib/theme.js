const KEY = 'fab-dispatch-theme'

export function loadTheme() {
  try { return localStorage.getItem(KEY) || 'system' } catch { return 'system' }
}

export function applyTheme(mode) {
  const root = document.documentElement
  if (mode === 'system') delete root.dataset.theme
  else root.dataset.theme = mode
  try { localStorage.setItem(KEY, mode) } catch { /* storage unavailable: theme still applies for this visit */ }
}
