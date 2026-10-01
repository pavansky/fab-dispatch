// Where to go for docs and support. One place, so every link in the app stays consistent.
export const REPO = 'https://github.com/pavansky/fab-dispatch'
export const DOCS = 'https://pavansky.github.io/fab-dispatch/'
export const LINKS = {
  docs: DOCS,
  apiReference: '/api/docs',
  privacy: `${DOCS}privacy/`,
  aiTransparency: `${DOCS}ai/`,
  changelog: `${REPO}/blob/main/CHANGELOG.md`,
  source: REPO,
  discussions: `${REPO}/discussions`,
  security: `${REPO}/security/policy`,
  support: `${DOCS}support/`,
}

/** A prefilled GitHub issue: what happened, plus the context a maintainer needs to reproduce it. */
export function reportProblemUrl({ title = 'Problem report', what = '', error = '', release = '', commit = '' } = {}) {
  const body = [
    '### What happened', what || '<!-- What did you do, and what did you expect? -->', '',
    '### Details', `- Page: \`${location.pathname}${location.search}\``, `- Release: ${release || 'unknown'} (${commit || 'unknown'})`,
    `- Browser: ${navigator.userAgent}`, error && `- Error: \`${String(error).slice(0, 300)}\``,
  ].filter((l) => l !== false && l !== '').join('\n')
  const q = new URLSearchParams({ labels: 'bug', title, body })
  return `${REPO}/issues/new?${q}`
}
