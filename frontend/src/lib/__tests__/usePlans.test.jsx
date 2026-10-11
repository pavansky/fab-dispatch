import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { usePlans } from '../usePlans.js'
import { ALGO_ORDER } from '../metrics.js'
import { errorBody, fixtures, json, mockApi } from '../../test/api.js'

const { scenario, plans, meta } = fixtures
const w1 = meta.default_weights
const w2 = { ...w1, travel_100m: w1.travel_100m + 1 }
const never = () => new Promise(() => {})
// The same job ids as the fixture shift, on a different floor (what a new seed produces).
const reseeded = { ...scenario, jobs: scenario.jobs.map((j) => ({ ...j, x: j.x + 1 })) }
const tagged = (body) => ({ ...plans[body.algorithm], label: `${body.algorithm}@${body.weights.travel_100m}` })

function solve(props, routes) {
  const api = mockApi({ 'POST /plan': ({ body }) => tagged(body), ...routes })
  const hook = renderHook((p) => usePlans(p.scenario, p.weights, { debounceMs: 0 }), { initialProps: props })
  return { api, ...hook }
}

describe('usePlans', () => {
  it('solves every strategy for the current inputs', async () => {
    const { result } = solve({ scenario, weights: w1 })
    await waitFor(() => expect(result.current.done).toBe(true))
    expect(result.current.results.map((r) => r.algorithm)).toEqual(ALGO_ORDER)
    expect(result.current.stale).toBe(false)
  })

  it('drops a plan whose re-solve failed instead of keeping the old-weight one', async () => {
    const api = mockApi({
      'POST /plan': ({ body }) => (body.algorithm === 'pyvrp' && body.weights.travel_100m === w2.travel_100m
        ? json(500, errorBody('internal', 'solver crashed')) : tagged(body)),
    })
    const { result, rerender } = renderHook((p) => usePlans(p.scenario, p.weights, { debounceMs: 0 }), { initialProps: { scenario, weights: w1 } })
    await waitFor(() => expect(result.current.done).toBe(true))
    rerender({ scenario, weights: w2 })
    await waitFor(() => expect(result.current.done).toBe(true))
    expect(api.find('POST', '/plan')).toHaveLength(10)
    expect(result.current.errors).toEqual({ pyvrp: 'solver crashed' })
    expect(result.current.results.map((r) => r.algorithm)).toEqual(['greedy', 'hungarian', 'regret', 'alns'])
    expect(result.current.results.every((r) => r.label.endsWith(`@${w2.travel_100m}`))).toBe(true)
  })

  it("never shows the previous shift's plans on a new shift with the same job ids", async () => {
    const { result, rerender } = solve({ scenario, weights: w1 }, {
      'POST /plan': ({ body }) => (body.scenario.jobs[0].x === reseeded.jobs[0].x ? never() : tagged(body)),
    })
    await waitFor(() => expect(result.current.done).toBe(true))
    rerender({ scenario: reseeded, weights: w1 })
    expect(result.current.results).toEqual([])
    expect([...result.current.pending]).toEqual(ALGO_ORDER)
    await new Promise((r) => setTimeout(r, 20))
    expect(result.current.results).toEqual([])
  })

  it('keeps the previous weights’ plans on screen, flagged stale, until the new ones are sent', async () => {
    const { result, rerender } = solve({ scenario, weights: w1 })
    await waitFor(() => expect(result.current.done).toBe(true))
    rerender({ scenario, weights: w2 })
    // Debouncing: old plans, all of them from the old weights, marked stale and pending.
    expect(result.current.stale).toBe(true)
    expect(result.current.done).toBe(false)
    expect(result.current.results.every((r) => r.label.endsWith(`@${w1.travel_100m}`))).toBe(true)
    await waitFor(() => expect(result.current.done).toBe(true))
    expect(result.current.stale).toBe(false)
    expect(result.current.results.every((r) => r.label.endsWith(`@${w2.travel_100m}`))).toBe(true)
  })

  it('never mixes plans solved for different weights', async () => {
    const { result, rerender } = solve({ scenario, weights: w1 }, {
      'POST /plan': ({ body }) => (body.weights.travel_100m === w2.travel_100m && body.algorithm !== 'greedy' ? never() : tagged(body)),
    })
    await waitFor(() => expect(result.current.done).toBe(true))
    rerender({ scenario, weights: w2 })
    await waitFor(() => expect(result.current.results.map((r) => r.algorithm)).toEqual(['greedy']))
    expect(result.current.results[0].label).toBe(`greedy@${w2.travel_100m}`)
    expect([...result.current.pending]).toEqual(['hungarian', 'regret', 'alns', 'pyvrp'])
  })

  it('reports strategies the API rate-limited apart from other errors, and can retry them', async () => {
    let limited = true
    const api = mockApi({
      'POST /plan': ({ body }) => (limited && body.algorithm !== 'greedy'
        ? json(429, errorBody('rate_limited', 'Too many requests'), { 'retry-after': '3600' })
        : body.algorithm === 'greedy' ? json(500, errorBody('internal', 'boom')) : tagged(body)),
    })
    const { result } = renderHook((p) => usePlans(p.scenario, p.weights, { debounceMs: 0 }), { initialProps: { scenario, weights: w1 } })
    await waitFor(() => expect(result.current.done).toBe(true))
    expect(result.current.rateLimited).toEqual(['hungarian', 'regret', 'alns', 'pyvrp'])
    expect(result.current.errors.greedy).toBe('boom')
    expect(api.find('POST', '/plan')).toHaveLength(5)
    limited = false
    act(() => result.current.retry())
    await waitFor(() => expect(result.current.results).toHaveLength(4))
    expect(result.current.rateLimited).toEqual([])
    expect(result.current.errors).toEqual({ greedy: 'boom' })
  })
})
