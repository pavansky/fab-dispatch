// Thin API client: one error shape, request cancellation, and a small response cache for
// deterministic POSTs (plans), so slider back-and-forth never re-hits the network.

export class ApiError extends Error {
  constructor(message, { status, code, requestId } = {}) {
    super(message)
    this.status = status
    this.code = code
    this.requestId = requestId
  }
}

const BASE = import.meta.env.VITE_API_BASE ?? '/api'

// The auth layer registers how to get the current access token; every request carries it.
let tokenProvider = () => null
export function setTokenProvider(fn) { tokenProvider = fn }
export const currentToken = () => tokenProvider()

const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`)

async function request(path, { method = 'GET', body, signal, headers, idempotent = false } = {}) {
  const token = tokenProvider()
  let res
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      signal,
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        // Retrying this exact request (flaky network) is answered once, not applied twice.
        ...(idempotent ? { 'Idempotency-Key': newKey() } : {}),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (e) {
    if (e.name === 'AbortError') throw e
    throw new ApiError("Can't reach the API. Is the backend running?", { status: 0, code: 'network' })
  }
  if (res.status === 304) return { notModified: true, etag: res.headers.get('etag') }
  const data = await res.json().catch(() => null)
  if (res.status === 401 && token) window.dispatchEvent(new Event('auth:expired'))
  if (!res.ok) {
    const err = data?.error
    throw new ApiError(err?.message ?? `${res.status} ${res.statusText}`,
      { status: res.status, code: err?.code, requestId: err?.request_id })
  }
  return { data, etag: res.headers.get('etag'), cache: res.headers.get('x-cache') }
}

// ------------------------------------------------------------------ cache for deterministic plans
const MAX_ENTRIES = 80
const planCache = new Map()
function remember(key, value) {
  planCache.delete(key)
  planCache.set(key, value)
  if (planCache.size > MAX_ENTRIES) planCache.delete(planCache.keys().next().value)
}
/** Forget cached plans (on sign-out, so the next session on this browser starts clean). */
export function clearPlanCache() { planCache.clear() }

export const getMeta = () => request('/meta').then((r) => r.data)
export const generateScenario = (params) => request('/scenario', { method: 'POST', body: params }).then((r) => r.data)

// ------------------------------------------------------------------ auth and fabs
export const authConfig = () => request('/auth/config').then((r) => r.data)
export const demoSignIn = (role) => request('/auth/demo', { method: 'POST', body: { role } }).then((r) => r.data)
export const getMe = () => request('/auth/me').then((r) => r.data)
export const listFabs = () => request('/fabs').then((r) => r.data)
export const getFab = (id) => request(`/fabs/${id}`).then((r) => r.data)

/** Plan one strategy. Resolves from the in-browser cache when the same request was made before. */
export async function plan(scenario, weights, algorithm, signal) {
  const body = { scenario, weights, algorithm }
  const key = JSON.stringify(body)
  if (planCache.has(key)) return { result: planCache.get(key), cache: 'browser' }
  const { data, cache } = await request('/plan', { method: 'POST', body, signal })
  remember(key, data)
  return { result: data, cache }
}

export const runBenchmark = (params, signal) => request('/benchmark', { method: 'POST', body: params, signal }).then((r) => r.data)
export const optimalityGap = (params, signal) => request('/optimality-gap', { method: 'POST', body: params, signal }).then((r) => r.data)

export const similarRepairs = (fabId, family, symptom, signal) =>
  request('/repairs/similar', { method: 'POST', body: { fab_id: fabId, family, symptom }, signal }).then((r) => r.data)
export const predictDurations = (scenario) =>
  request('/repairs/predict-durations', { method: 'POST', body: scenario }).then((r) => r.data)

// ------------------------------------------------------------------ live shifts
export const createShift = (scenario, weights, algorithm) =>
  request('/shifts', { method: 'POST', body: { scenario, weights, algorithm } }).then((r) => r.data)
export const getShift = (id, etag) =>
  request(`/shifts/${id}`, { headers: etag ? { 'If-None-Match': etag } : undefined })
export const listShifts = (fabId) => request(`/shifts?fab_id=${encodeURIComponent(fabId)}`).then((r) => r.data)
export const advanceShift = (id, minutes) =>
  request(`/shifts/${id}/advance`, { method: 'POST', body: { minutes }, idempotent: true }).then((r) => r.data)
export const releaseClock = (id) => request(`/shifts/${id}/release`, { method: 'POST' }).then((r) => r.data)
export const reportJob = (id, job) =>
  request(`/shifts/${id}/jobs`, { method: 'POST', body: { job }, idempotent: true }).then((r) => r.data)
export const engineerOff = (id, engineerId) =>
  request(`/shifts/${id}/engineers/${engineerId}/off`, { method: 'POST', idempotent: true }).then((r) => r.data)
export const shiftEvents = (id, after = 0) => request(`/shifts/${id}/events?after=${after}`).then((r) => r.data)
// EventSource can't send headers, so the stream (only) takes the token as a query parameter.
export const streamUrl = (id) => `${BASE}/shifts/${id}/stream?access_token=${encodeURIComponent(tokenProvider() ?? '')}`

// ------------------------------------------------------------------ help and assistant
export const helpIndex = () => request('/help').then((r) => r.data)
export const helpArticle = (slug) => request(`/help/${encodeURIComponent(slug)}`).then((r) => r.data)
export const helpSearch = (q, signal) => request(`/help/search?q=${encodeURIComponent(q)}`, { signal }).then((r) => r.data)
export const askAssistant = (question, context) =>
  request('/assistant/ask', { method: 'POST', body: { question, context } }).then((r) => r.data)
