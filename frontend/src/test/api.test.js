import { describe, expect, it, vi } from 'vitest'
import { ApiError, advanceShift, engineerOff, getHealth, getMeta, plan, releaseClock, reportJob, retryAfterMs, setTokenProvider, setTokenRefresher, streamUrl, streamUrlFor } from '../api.js'
import { errorBody, fixtures, json, mockApi } from './api.js'

describe('API client', () => {
  it('sends the current access token on every request', async () => {
    const api = mockApi({ 'GET /meta': fixtures.meta })
    setTokenProvider(() => 'tok-123')
    await getMeta()
    expect(api.calls[0].headers.Authorization).toBe('Bearer tok-123')
  })

  it('sends no Authorization header when signed out', async () => {
    const api = mockApi({ 'GET /meta': fixtures.meta })
    setTokenProvider(() => null)
    await getMeta()
    expect(api.calls[0].headers).not.toHaveProperty('Authorization')
  })

  it('turns the error envelope into an ApiError with code, status and request id', async () => {
    mockApi({ 'GET /meta': json(429, errorBody('rate_limited', 'Too many requests')) })
    setTokenProvider(() => null)
    const err = await getMeta().catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ message: 'Too many requests', status: 429, code: 'rate_limited', requestId: 'req-test' })
  })

  it('explains a network failure in plain words', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const err = await getMeta().catch((e) => e)
    expect(err.code).toBe('network')
    expect(err.message).toBe("Can't reach the API. Is the backend running?")
  })

  it('signals an expired session when a signed-in request gets 401', async () => {
    mockApi({ 'GET /meta': json(401, errorBody('unauthorized', 'Token expired')) })
    setTokenProvider(() => 'stale')
    const expired = vi.fn()
    window.addEventListener('auth:expired', expired)
    await getMeta().catch(() => {})
    window.removeEventListener('auth:expired', expired)
    expect(expired).toHaveBeenCalledOnce()
  })

  it('renews the session once on a 401 and retries with the new token, signing out only if that fails', async () => {
    let token = 'stale'
    const api = mockApi({ 'GET /meta': ({ headers }) => (headers.Authorization === 'Bearer fresh' ? fixtures.meta : json(401, errorBody('unauthorized', 'Token expired'))) })
    setTokenProvider(() => token)
    const refresher = vi.fn(async () => { token = 'fresh'; return 'fresh' })
    setTokenRefresher(refresher)
    const expired = vi.fn()
    window.addEventListener('auth:expired', expired)
    try {
      await expect(Promise.all([getMeta(), getMeta()])).resolves.toEqual([fixtures.meta, fixtures.meta])
      expect(refresher).toHaveBeenCalledOnce() // one renewal serves both requests
      expect(api.find('GET', '/meta').map((c) => c.headers.Authorization)).toEqual(['Bearer stale', 'Bearer stale', 'Bearer fresh', 'Bearer fresh'])
      expect(expired).not.toHaveBeenCalled()

      setTokenRefresher(async () => null) // the refresh token is gone too
      token = 'stale'
      await expect(getMeta()).rejects.toMatchObject({ status: 401 })
      expect(expired).toHaveBeenCalledOnce()
    } finally {
      window.removeEventListener('auth:expired', expired)
    }
  })

  it('sends the live-action pin as If-Match, and nothing when the caller has no version', async () => {
    const api = mockApi({ 'POST /shifts/s1/advance': {}, 'POST /shifts/s1/release': {}, 'POST /shifts/s1/engineers/E1/off': {} })
    await advanceShift('s1', 30, { etag: '"4-abcd"' })
    await releaseClock('s1', { etag: '"4"' })
    await engineerOff('s1', 'E1')
    expect(api.calls.map((c) => c.headers['If-Match'])).toEqual(['"4-abcd"', '"4"', undefined])
  })

  it('makes live actions retry-safe with a fresh idempotency key per action', async () => {
    const api = mockApi({ 'POST /shifts/s1/advance': {}, 'POST /shifts/s1/jobs': {} })
    setTokenProvider(() => 't')
    await advanceShift('s1', 30)
    await reportJob('s1', { id: 'J999' })
    const keys = api.calls.map((c) => c.headers['Idempotency-Key'])
    expect(keys.every(Boolean)).toBe(true)
    expect(new Set(keys).size).toBe(2)
    expect(api.calls[0].body).toEqual({ minutes: 30 })
  })

  it('retries a live action on a dropped connection with the same idempotency key', async () => {
    const api = mockApi({ 'POST /shifts/s1/advance': { ok: true } })
    const real = api.fetchMock.getMockImplementation()
    api.fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError('Failed to fetch'))).mockImplementation(real)
    setTokenProvider(() => 't')
    await expect(advanceShift('s1', 30)).resolves.toEqual({ ok: true })
    expect(api.fetchMock).toHaveBeenCalledTimes(2)
    const keys = api.fetchMock.mock.calls.map(([, init]) => init.headers['Idempotency-Key'])
    expect(keys[0]).toBeTruthy()
    expect(keys[1]).toBe(keys[0])
  })

  it('retries a gateway failure on a live action, but never a plain read', async () => {
    let n = 0
    const api = mockApi({
      'POST /shifts/s1/jobs': () => (++n === 1 ? json(503, errorBody('unavailable', 'try again')) : { ok: true }),
      'GET /meta': json(503, errorBody('unavailable', 'try again')),
    })
    await expect(reportJob('s1', { id: 'L1' })).resolves.toEqual({ ok: true })
    expect(api.find('POST', '/shifts/s1/jobs')).toHaveLength(2)
    await expect(getMeta()).rejects.toMatchObject({ status: 503 })
    expect(api.find('GET', '/meta')).toHaveLength(1)
  })

  it('serves a repeated plan request from the browser cache', async () => {
    const api = mockApi({ 'POST /plan': fixtures.plans.greedy })
    const scenario = { ...fixtures.scenario, id: 'cache-test' }
    const first = await plan(scenario, fixtures.meta.default_weights, 'greedy')
    const second = await plan(scenario, fixtures.meta.default_weights, 'greedy')
    expect(api.find('POST', '/plan')).toHaveLength(1)
    expect(second.cache).toBe('browser')
    expect(second.result).toEqual(first.result)
  })

  it('shares one request between identical plan requests in flight', async () => {
    const release = {}
    const api = mockApi({ 'POST /plan': ({ body }) => new Promise((r) => { release[body.algorithm] = () => r(fixtures.plans[body.algorithm]) }) })
    const scenario = { ...fixtures.scenario, id: 'dedupe-test' }
    const first = plan(scenario, fixtures.meta.default_weights, 'greedy')
    const second = plan(scenario, fixtures.meta.default_weights, 'greedy')
    const other = plan(scenario, fixtures.meta.default_weights, 'alns')
    await new Promise((r) => setTimeout(r, 0))
    expect(api.find('POST', '/plan')).toHaveLength(2) // greedy once, alns once
    release.greedy(); release.alns()
    expect((await first).result).toEqual(fixtures.plans.greedy)
    expect((await second).result).toEqual(fixtures.plans.greedy)
    await expect(other).resolves.toBeTruthy()
  })

  it('drops only the caller that aborts; the shared solve runs on and fills the cache', async () => {
    let release
    const api = mockApi({ 'POST /plan': () => new Promise((r) => { release = () => r(fixtures.plans.greedy) }) })
    const scenario = { ...fixtures.scenario, id: 'abort-test' }
    const ctrl = new AbortController()
    const dropped = plan(scenario, fixtures.meta.default_weights, 'greedy', ctrl.signal)
    const kept = plan(scenario, fixtures.meta.default_weights, 'greedy')
    ctrl.abort()
    await expect(dropped).rejects.toMatchObject({ name: 'AbortError' })
    release()
    expect((await kept).cache).not.toBe('browser')
    expect((await plan(scenario, fixtures.meta.default_weights, 'greedy')).cache).toBe('browser')
    expect(api.find('POST', '/plan')).toHaveLength(1)
  })

  it('retries a 429 once after the Retry-After the server asks for, then gives up', async () => {
    let n = 0
    const api = mockApi({
      'GET /meta': () => (++n === 1 ? json(429, errorBody('rate_limited', 'slow down'), { 'retry-after': '0' }) : fixtures.meta),
      'GET /health': json(429, errorBody('rate_limited', 'still too fast'), { 'retry-after': '0' }),
    })
    await expect(getMeta()).resolves.toEqual(fixtures.meta)
    expect(api.find('GET', '/meta')).toHaveLength(2)
    await expect(getHealth()).rejects.toMatchObject({ status: 429, code: 'rate_limited' })
    expect(api.find('GET', '/health')).toHaveLength(2) // one retry, not a storm
  })

  it('does not wait out a Retry-After longer than the UI can stand', async () => {
    const api = mockApi({ 'GET /meta': json(429, errorBody('rate_limited', 'come back later'), { 'retry-after': '3600' }) })
    await expect(getMeta()).rejects.toMatchObject({ status: 429 })
    expect(api.find('GET', '/meta')).toHaveLength(1)
    expect(retryAfterMs(new Response(null, { headers: { 'retry-after': '2' } }))).toBe(2000)
    expect(retryAfterMs(new Response(null, { headers: { 'retry-after': new Date(Date.now() + 1500).toUTCString() } }))).toBeGreaterThan(0)
    expect(retryAfterMs(new Response(null))).toBe(1000)
  })

  it('opens the stream with a ticket, or the token where the API has none (encoded: EventSource cannot send headers)', async () => {
    setTokenProvider(() => 'a b&c')
    expect(streamUrl('s1')).toBe('/api/shifts/s1/stream?access_token=a+b%26c')
    expect(streamUrl('s1', { ticket: 't/1', after: 12 })).toBe('/api/shifts/s1/stream?ticket=t%2F1&after=12')
    const api = mockApi({ 'POST /shifts/s1/stream-ticket': { ticket: 'tk', expires_in: 90 }, 'POST /shifts/s2/stream-ticket': json(404, errorBody('not_found', 'nope')) })
    expect(await streamUrlFor('s1', 3)).toBe('/api/shifts/s1/stream?ticket=tk&after=3')
    expect(await streamUrlFor('s2')).toBe('/api/shifts/s2/stream?access_token=a+b%26c')
    expect(api.find('POST', '/shifts/s1/stream-ticket')[0].headers.Authorization).toBe('Bearer a b&c')
  })
})
