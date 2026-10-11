// The benchmark's verdicts: per preset, every strategy against the cheapest over the same
// seeded shifts, with one Holm adjustment across every comparison in the run.
import { ALGO_ORDER } from './metrics.js'
import { holm, mean, pairedCI } from './stats.js'

/** Seeds below this give approximate intervals: the t interval assumes near-normal differences. */
export const FEW_SEEDS = 10

const finite = (xs) => xs.filter(Number.isFinite)
const meanOf = (xs) => (finite(xs).length ? mean(finite(xs)) : NaN)

/**
 * runs: [{ preset, seed, algorithm, metrics }], presets: the presets in display order.
 * Returns { comparisons, presets: { [preset]: analysis } } for presets with any run, where an
 * analysis has: seedsRun, algos, series(a, key), meanCost, latency, best, vsBest[a] (the
 * Holm-adjusted paired interval against the cheapest, or null for the cheapest itself),
 * verdict(a) ∈ 'lowest' | 'costlier' | 'notsig' | 'nodata', value (the best-value strategy)
 * and notSig (strategies not shown to differ from the cheapest).
 */
export function analyseBenchmark(runs, presets, { alpha = 0.05 } = {}) {
  const out = {}
  const tests = [] // every comparison in the run, for one Holm adjustment
  for (const p of presets) {
    const rs = runs.filter((r) => r.preset === p)
    if (!rs.length) continue
    const seedsRun = [...new Set(rs.map((r) => r.seed))].sort((a, b) => a - b)
    const algos = ALGO_ORDER.filter((a) => rs.some((r) => r.algorithm === a))
    const series = (a, k) => seedsRun.map((sd) => {
      const v = rs.find((r) => r.algorithm === a && r.seed === sd)?.metrics?.[k]
      return typeof v === 'number' ? v : NaN
    })
    const meanCost = Object.fromEntries(algos.map((a) => [a, meanOf(series(a, 'objective'))]))
    const latency = Object.fromEntries(algos.map((a) => [a, meanOf(series(a, 'runtime_ms'))]))
    const withCost = algos.filter((a) => Number.isFinite(meanCost[a]))
    const best = withCost.length ? withCost.reduce((x, y) => (meanCost[y] < meanCost[x] ? y : x)) : null
    const vsBest = Object.fromEntries(algos.map((a) => [a, null]))
    if (best) {
      for (const a of algos) {
        if (a === best) continue
        const raw = pairedCI(series(a, 'objective'), series(best, 'objective'), { alpha })
        vsBest[a] = raw
        tests.push({ preset: p, algo: a, a: series(a, 'objective'), b: series(best, 'objective'), p: raw.p })
      }
    }
    out[p] = { runs: rs, seedsRun, algos, series, meanCost, latency, best, vsBest, fewSeeds: seedsRun.length < FEW_SEEDS }
  }
  const adj = holm(tests.map((t) => t.p), { alpha })
  tests.forEach((t, i) => {
    // Rebuild the interval at the level Holm tested this comparison at, so it excludes 0
    // exactly when the verdict says "costlier".
    const ci = pairedCI(t.a, t.b, { alpha: adj.level[i] })
    out[t.preset].vsBest[t.algo] = { ...ci, reject: adj.reject[i], adjusted: adj.adjusted[i], level: adj.level[i] }
  })
  for (const p of Object.keys(out)) {
    const an = out[p]
    an.verdict = (a) => {
      if (a === an.best) return 'lowest'
      const ci = an.vsBest[a]
      if (!ci || !(ci.n >= 2)) return 'nodata'
      return ci.reject ? 'costlier' : 'notsig'
    }
    const tied = an.algos.filter((a) => a === an.best || an.verdict(a) === 'notsig').filter((a) => Number.isFinite(an.latency[a]))
    an.value = tied.length ? tied.reduce((x, y) => (an.latency[y] < an.latency[x] ? y : x)) : an.best
    an.notSig = an.algos.filter((a) => an.verdict(a) === 'notsig')
    an.noData = an.algos.filter((a) => an.verdict(a) === 'nodata')
  }
  return { comparisons: adj.m, presets: out }
}

/** Rough first-run time: 0.8 s per (seed × preset) on the reference shift of 14 engineers × 45 jobs. */
export function estimateSeconds(seeds, presetCount, { n_engineers = 14, n_jobs = 45 } = {}) {
  const scale = (Math.max(1, n_engineers) * Math.max(1, Math.min(n_jobs, 120))) / (14 * 45)
  return Math.max(1, Math.round(seeds * presetCount * 0.8 * scale))
}
