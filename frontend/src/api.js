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

async function request(path, { method = 'GET', body, signal, headers } = {}) {
  let res
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      signal,
      headers: { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...headers },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (e) {
    if (e.name === 'AbortError') throw e
    throw new ApiError("Can't reach the API. Is the backend running?", { status: 0, code: 'network' })
  }
  if (res.status === 304) return { notModified: true, etag: res.headers.get('etag') }
  const data = await res.json().catch(() => null)
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

export const getMeta = () => request('/meta').then((r) => r.data)
export const generateScenario = (params) => request('/scenario', { method: 'POST', body: params }).then((r) => r.data)

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

export const similarRepairs = (family, symptom, signal) =>
  request('/repairs/similar', { method: 'POST', body: { family, symptom }, signal }).then((r) => r.data)
export const predictDurations = (scenario) =>
  request('/repairs/predict-durations', { method: 'POST', body: scenario }).then((r) => r.data)

// ------------------------------------------------------------------ live shifts
export const createShift = (scenario, weights, algorithm) =>
  request('/shifts', { method: 'POST', body: { scenario, weights, algorithm } }).then((r) => r.data)
export const getShift = (id, etag) =>
  request(`/shifts/${id}`, { headers: etag ? { 'If-None-Match': etag } : undefined })
export const advanceShift = (id, minutes) =>
  request(`/shifts/${id}/advance`, { method: 'POST', body: { minutes } }).then((r) => r.data)
export const reportJob = (id, job) =>
  request(`/shifts/${id}/jobs`, { method: 'POST', body: { job } }).then((r) => r.data)
export const engineerOff = (id, engineerId) =>
  request(`/shifts/${id}/engineers/${engineerId}/off`, { method: 'POST' }).then((r) => r.data)
export const shiftEvents = (id, after = 0) => request(`/shifts/${id}/events?after=${after}`).then((r) => r.data)
export const streamUrl = (id) => `${BASE}/shifts/${id}/stream`
