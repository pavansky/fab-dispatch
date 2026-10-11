import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
 *
 * Returns { results, pending, errors, rateLimited, cacheInfo, done, stale, retry }:
 *  - results: plans for the inputs shown; pending: strategies still solving for the current inputs;
 *  - errors: strategy → message for the current inputs; rateLimited: the strategies among them the
 *    API refused with 429 (shown as one notice, not one error bar each); retry() re-sends those inputs;
 *  - cacheInfo: strategy → where its plan came from; done: nothing pending;
 *  - stale: true while the plans on screen were solved for different (previous) inputs than the
 *    current ones and a newer request is pending.
 */
export function usePlans(scenario, weights, { debounceMs = 200 } = {}) {
  const sKey = useMemo(() => (scenario ? keyOf(scenario) : null), [scenario])
  const wKey = useMemo(() => (weights ? keyOf(weights) : null), [weights])
  const key = sKey && wKey ? `${sKey}|${wKey}` : null
  // The inputs last sent to the solvers, and each strategy's latest answer.
  const [sent, setSent] = useState(null)
  const [answers, setAnswers] = useState({})
  const [attempt, setAttempt] = useState(0) // bumped by retry(): the same inputs, sent again
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
            if (e.name !== 'AbortError' && !c.signal.aborted) setAnswers((prev) => ({ ...prev, [algo]: { key: k, error: e.message, status: e.status } }))
          })
      })
    }, debounceMs)
    return () => clearTimeout(t)
  }, [scenario, weights, sKey, wKey, debounceMs, attempt])

  useEffect(() => () => ctrl.current?.abort(), [])

  // Answers for these exact inputs; or, while new weights are still debouncing, the last
  // answers for this same shift (stale). Never answers for a different shift.
  const fresh = Boolean(key) && sent?.key === key
  const stale = !fresh && Boolean(sKey) && sent?.sKey === sKey
  const shownKey = fresh || stale ? sent.key : null
  const shown = ALGO_ORDER.filter((a) => shownKey && answers[a]?.key === shownKey)
  const results = shown.filter((a) => answers[a].result).map((a) => answers[a].result)
  const failed = fresh ? shown.filter((a) => answers[a].error) : []
  const errors = Object.fromEntries(failed.map((a) => [a, answers[a].error]))
  const rateLimited = failed.filter((a) => answers[a].status === 429)
  const cacheInfo = Object.fromEntries(shown.filter((a) => answers[a].result).map((a) => [a, answers[a].cache]))
  const pending = new Set(fresh ? ALGO_ORDER.filter((a) => !shown.includes(a)) : key ? ALGO_ORDER : [])
  const retry = useCallback(() => setAttempt((n) => n + 1), [])
  return { results, pending, errors, rateLimited, cacheInfo, done: pending.size === 0, stale: stale && results.length > 0, retry }
}
