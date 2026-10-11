import { describe, expect, it, vi } from 'vitest'
import { ApiError, advanceShift, getMeta, plan, reportJob, setTokenProvider, streamUrl } from '../api.js'
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

  it('puts the token in the stream URL, encoded (EventSource cannot send headers)', () => {
    setTokenProvider(() => 'a b&c')
    expect(streamUrl('s1')).toBe('/api/shifts/s1/stream?access_token=a%20b%26c')
  })
})
