import { useEffect, useRef, useState } from 'react'
import { plan } from '../api.js'
import { ALGO_ORDER } from './metrics.js'

/**
 * Plan the shift with every strategy at once and render each result as it lands, fast
 * ones first. A new input cancels requests still in flight, and the previous results stay
 * on screen (marked stale) until the new ones arrive, so the UI never blanks while solving.
 */
export function usePlans(scenario, weights, { debounceMs = 200 } = {}) {
  const [byAlgo, setByAlgo] = useState({})
  const [pending, setPending] = useState(() => new Set())
  const [errors, setErrors] = useState({})
  const [cacheInfo, setCacheInfo] = useState({})
  const ctrl = useRef(null)

  useEffect(() => {
    if (!scenario || !weights) return
    const t = setTimeout(() => {
      ctrl.current?.abort()
      const c = new AbortController()
      ctrl.current = c
      setPending(new Set(ALGO_ORDER))
      setErrors({})
      ALGO_ORDER.forEach((algo) => {
        plan(scenario, weights, algo, c.signal)
          .then(({ result, cache }) => {
            if (c.signal.aborted) return
            setByAlgo((prev) => ({ ...prev, [algo]: result }))
            setCacheInfo((prev) => ({ ...prev, [algo]: cache }))
          })
          .catch((e) => { if (e.name !== 'AbortError') setErrors((prev) => ({ ...prev, [algo]: e.message })) })
          .finally(() => {
            if (!c.signal.aborted) setPending((prev) => { const n = new Set(prev); n.delete(algo); return n })
          })
      })
    }, debounceMs)
    return () => clearTimeout(t)
  }, [scenario, weights, debounceMs])

  useEffect(() => () => ctrl.current?.abort(), [])

  // A stale plan is only shown while every job it references still exists.
  const known = new Set(scenario?.jobs.map((j) => j.id) ?? [])
  const results = ALGO_ORDER.map((a) => byAlgo[a])
    .filter((r) => r && r.assignments.every((x) => known.has(x.job_id)) && r.unassigned.every((x) => known.has(x.job_id)))
  return { results, pending, errors, cacheInfo, done: pending.size === 0 }
}
