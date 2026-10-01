const KEY = 'fab-dispatch-theme'

export function loadTheme() {
  // Light by default; dark and auto (follow the OS) are opt-in.
  try { return localStorage.getItem(KEY) || 'light' } catch { return 'light' }
}

export function applyTheme(mode) {
  const root = document.documentElement
  if (mode === 'system') delete root.dataset.theme
  else root.dataset.theme = mode
  try { localStorage.setItem(KEY, mode) } catch { /* storage unavailable: theme still applies for this visit */ }
}
