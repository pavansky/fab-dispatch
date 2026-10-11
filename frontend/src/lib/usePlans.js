import { useEffect, useMemo, useRef, useState } from 'react'
import { plan } from '../api.js'
import { ALGO_ORDER } from './metrics.js'

const keyOf = (x) => JSON.stringify(x)

/**
 * Plan the shift with every strategy at once and render each result as it lands, fast
 * ones first. A new input cancels requests still in flight.
 *
 * Every answer (plan or error) is tagged with the exact inputs it was solved for, and only
 * answers for the current inputs are returned, so plans solved for different weights are
 * never compared, a failed re-solve never leaves an old plan behind, and a plan for another
 * shift (a new seed reuses the same job ids) is never drawn on this one. The one exception:
 * while new weights wait out the debounce, the previous weights' plans stay on screen,
 * flagged `stale`, so dragging a slider doesn't blank the page.
 */
export function usePlans(scenario, weights, { debounceMs = 200 } = {}) {
  const sKey = useMemo(() => (scenario ? keyOf(scenario) : null), [scenario])
  const wKey = useMemo(() => (weights ? keyOf(weights) : null), [weights])
  const key = sKey && wKey ? `${sKey}|${wKey}` : null
  // The inputs last sent to the solvers, and each strategy's latest answer.
  const [sent, setSent] = useState(null)
  const [answers, setAnswers] = useState({})
  const ctrl = useRef(null)

  useEffect(() => {
    if (!scenario || !weights) return
    const k = `${sKey}|${wKey}`
    const t = setTimeout(() => {
      ctrl.current?.abort()
      const c = new AbortController()
      ctrl.current = c
      setSent({ key: k, sKey })
      ALGO_ORDER.forEach((algo) => {
        plan(scenario, weights, algo, c.signal)
          .then(({ result, cache }) => {
            if (!c.signal.aborted) setAnswers((prev) => ({ ...prev, [algo]: { key: k, result, cache } }))
          })
          .catch((e) => {
            if (e.name !== 'AbortError' && !c.signal.aborted) setAnswers((prev) => ({ ...prev, [algo]: { key: k, error: e.message } }))
          })
      })
    }, debounceMs)
    return () => clearTimeout(t)
  }, [scenario, weights, sKey, wKey, debounceMs])

  useEffect(() => () => ctrl.current?.abort(), [])

  // Answers for these exact inputs; or, while new weights are still debouncing, the last
  // answers for this same shift (stale). Never answers for a different shift.
  const fresh = Boolean(key) && sent?.key === key
  const stale = !fresh && Boolean(sKey) && sent?.sKey === sKey
  const shownKey = fresh || stale ? sent.key : null
  const shown = ALGO_ORDER.filter((a) => shownKey && answers[a]?.key === shownKey)
  const results = shown.filter((a) => answers[a].result).map((a) => answers[a].result)
  const errors = fresh ? Object.fromEntries(shown.filter((a) => answers[a].error).map((a) => [a, answers[a].error])) : {}
  const cacheInfo = Object.fromEntries(shown.filter((a) => answers[a].result).map((a) => [a, answers[a].cache]))
  const pending = new Set(fresh ? ALGO_ORDER.filter((a) => !shown.includes(a)) : key ? ALGO_ORDER : [])
  return { results, pending, errors, cacheInfo, done: pending.size === 0, stale: stale && results.length > 0 }
}
