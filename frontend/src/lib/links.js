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
  license: `${DOCS}project/license/`,
  terms: `${DOCS}terms/`,
}

// Only these query parameters go into a report: which fab and view. The rest of the URL can
// name a live shift (its id is the join link), a job or an engineer, and stays private.
const REPORT_PARAMS = ['fab', 'tab']
const EMAIL = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi

/** The page for a report: path plus the fab and tab parameters only. */
export function reportPage(loc = location) {
  const q = new URLSearchParams(loc.search)
  const kept = new URLSearchParams()
  for (const k of REPORT_PARAMS) if (q.has(k)) kept.set(k, q.get(k))
  return `${loc.pathname}${kept.size ? `?${kept}` : ''}`
}

/** Error text for a report: cut short, with any email address (another user's, say) redacted. */
export function redactError(error) {
  return String(error).slice(0, 300).replace(EMAIL, '[email redacted]')
}

/** A prefilled GitHub issue: what happened, plus the context a maintainer needs to reproduce it. */
export function reportProblemUrl({ title = 'Problem report', what = '', error = '', release = '', commit = '' } = {}) {
  const body = [
    '### What happened', what || '<!-- What did you do, and what did you expect? -->', '',
    '### Details', `- Page: \`${reportPage()}\``, `- Release: ${release || 'unknown'} (${commit || 'unknown'})`,
    `- Browser: ${navigator.userAgent}`, error && `- Error: \`${redactError(error)}\``,
  ].filter((l) => l !== false && l !== '').join('\n')
  const q = new URLSearchParams({ labels: 'bug', title, body })
  return `${REPO}/issues/new?${q}`
}
