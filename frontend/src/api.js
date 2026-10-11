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
const abortError = () => new DOMException('The request was aborted', 'AbortError')
/** Wait, unless the signal aborts first. */
const sleep = (ms, signal) => new Promise((resolve, reject) => {
  if (signal?.aborted) { reject(abortError()); return }
  const t = setTimeout(() => { signal?.removeEventListener('abort', onAbort); resolve() }, ms)
  function onAbort() { clearTimeout(t); reject(abortError()) }
  signal?.addEventListener('abort', onAbort, { once: true })
})
const RETRY_STATUS = new Set([502, 503, 504])
export const RETRY_DELAYS_MS = [250, 750]
/** The longest a 429's Retry-After is honoured for; beyond that the error shows instead. */
export const RETRY_AFTER_MAX_MS = 15000

/** Milliseconds a 429 asks us to wait: a Retry-After in seconds or as an HTTP date, else 1 s. */
export function retryAfterMs(res) {
  const raw = res.headers.get('retry-after')
  if (!raw) return 1000
  if (/^\d+$/.test(raw.trim())) return Number(raw) * 1000
  const at = Date.parse(raw)
  return Number.isNaN(at) ? 1000 : Math.max(0, at - Date.now())
}

/**
 * `idempotencyKey` marks one logical action. If the connection drops or a gateway fails, the
 * request is retried with the same key, so the server answers the retry from its record of
 * the first attempt instead of applying the action twice. Requests without a key are never
 * retried. (Double clicks are a UI concern: the live view disables its buttons in flight.)
 */
async function request(path, { method = 'GET', body, signal, headers, idempotencyKey } = {}) {
  const token = tokenProvider()
  const delays = idempotencyKey ? RETRY_DELAYS_MS : []
  let res
  let rateLimited = false // a 429 is retried once, after the Retry-After the server asks for
  for (let attempt = 0; ; attempt++) {
    try {
      res = await fetch(`${BASE}${path}`, {
        method,
        signal,
        headers: {
          ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}),
          ...headers,
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      })
    } catch (e) {
      if (e.name === 'AbortError') throw e
      if (attempt < delays.length) { await sleep(delays[attempt], signal); continue }
      throw new ApiError("Can't reach the API. Is the backend running?", { status: 0, code: 'network' })
    }
    if (RETRY_STATUS.has(res.status) && attempt < delays.length) { await sleep(delays[attempt], signal); continue }
    if (res.status === 429 && !rateLimited) {
      const wait = retryAfterMs(res)
      if (wait <= RETRY_AFTER_MAX_MS) { rateLimited = true; await sleep(wait, signal); continue }
    }
    break
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
const inFlight = new Map() // body → promise of the plan request in flight for it
function remember(key, value) {
  planCache.delete(key)
  planCache.set(key, value)
  if (planCache.size > MAX_ENTRIES) planCache.delete(planCache.keys().next().value)
}
/** Forget cached and in-flight plans (on sign-out, so the next session on this browser starts clean). */
export function clearPlanCache() { planCache.clear(); inFlight.clear() }

export const getMeta = () => request('/meta').then((r) => r.data)
export const generateScenario = (params, signal) => request('/scenario', { method: 'POST', body: params, signal }).then((r) => r.data)

// ------------------------------------------------------------------ auth and fabs
export const authConfig = () => request('/auth/config').then((r) => r.data)
export const demoSignIn = (role) => request('/auth/demo', { method: 'POST', body: { role } }).then((r) => r.data)
export const getMe = () => request('/auth/me').then((r) => r.data)
export const listFabs = () => request('/fabs').then((r) => r.data)
export const getFab = (id) => request(`/fabs/${id}`).then((r) => r.data)

// Identical plan requests in flight share one fetch: a slider nudged back to a value whose
// solve is still running joins that solve instead of starting a second one. Dropping a
// caller (its signal aborts) rejects that caller only; the solve runs on, since the server
// works on it regardless, and its answer lands in the cache for the next request.
const forCaller = (promise, signal) => new Promise((resolve, reject) => {
  if (signal?.aborted) { reject(abortError()); return }
  const onAbort = () => reject(abortError())
  signal?.addEventListener('abort', onAbort, { once: true })
  promise.then(resolve, reject).finally(() => signal?.removeEventListener('abort', onAbort))
})

/** Plan one strategy. Resolves from the in-browser cache when the same request was made before. */
export function plan(scenario, weights, algorithm, signal) {
  const body = { scenario, weights, algorithm }
  const key = JSON.stringify(body)
  if (planCache.has(key)) return Promise.resolve({ result: planCache.get(key), cache: 'browser' })
  if (!inFlight.has(key)) {
    const p = request('/plan', { method: 'POST', body })
      .then(({ data, cache }) => { remember(key, data); return { result: data, cache } })
      .finally(() => { if (inFlight.get(key) === p) inFlight.delete(key) })
    inFlight.set(key, p)
  }
  return forCaller(inFlight.get(key), signal)
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
  request(`/shifts/${id}/advance`, { method: 'POST', body: { minutes }, idempotencyKey: newKey() }).then((r) => r.data)
export const releaseClock = (id) => request(`/shifts/${id}/release`, { method: 'POST' }).then((r) => r.data)
export const reportJob = (id, job) =>
  request(`/shifts/${id}/jobs`, { method: 'POST', body: { job }, idempotencyKey: newKey() }).then((r) => r.data)
export const engineerOff = (id, engineerId) =>
  request(`/shifts/${id}/engineers/${engineerId}/off`, { method: 'POST', idempotencyKey: newKey() }).then((r) => r.data)
export const shiftEvents = (id, after = 0) => request(`/shifts/${id}/events?after=${after}`).then((r) => r.data)
// EventSource can't send headers, so the stream (only) takes the token as a query parameter.
export const streamUrl = (id) => `${BASE}/shifts/${id}/stream?access_token=${encodeURIComponent(tokenProvider() ?? '')}`

// ------------------------------------------------------------------ help and assistant
export const helpIndex = () => request('/help').then((r) => r.data)
export const helpArticle = (slug) => request(`/help/${encodeURIComponent(slug)}`).then((r) => r.data)
export const helpSearch = (q, signal) => request(`/help/search?q=${encodeURIComponent(q)}`, { signal }).then((r) => r.data)
export const getHealth = () => request('/health').then((r) => r.data)
export const deleteAccount = () => request('/auth/me', { method: 'DELETE' }).then((r) => r.data)
export const sendFeedback = (feedback) => request('/assistant/feedback', { method: 'POST', body: feedback })
export const askAssistant = (question, context) =>
  request('/assistant/ask', { method: 'POST', body: { question, context } }).then((r) => r.data)
