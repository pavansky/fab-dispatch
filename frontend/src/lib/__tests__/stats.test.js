import { describe, expect, it } from 'vitest'
import { holm, pairedBootstrapCI, pairedCI, pairedTCI, tCDF, tQuantile, unpairedTCI } from '../stats.js'
import { paretoFront, recommend } from '../analysis.js'

describe('pairedBootstrapCI', () => {
  it('excludes zero for a consistent difference', () => {
    const a = [10, 12, 11, 13, 12, 11, 10, 12], b = a.map((x) => x - 3)
    const ci = pairedBootstrapCI(a, b)
    expect(ci.lo).toBeGreaterThan(0)
  })
  it('includes zero for noise, so no win is declared', () => {
    const a = [10, 12, 9, 11, 10, 12, 9, 11], b = [11, 11, 10, 10, 11, 11, 10, 10]
    const ci = pairedBootstrapCI(a, b)
    expect(ci.lo).toBeLessThan(0)
    expect(ci.hi).toBeGreaterThan(0)
  })
  it('is deterministic', () => {
    expect(pairedBootstrapCI([1, 2, 3], [0, 0, 1])).toEqual(pairedBootstrapCI([1, 2, 3], [0, 0, 1]))
  })
})

describe('pairedTCI', () => {
  it('matches Student t critical values', () => {
    // t(0.975, df): 4 → 2.776, 9 → 2.262, 19 → 2.093, 29 → 2.045
    expect(tQuantile(0.975, 4)).toBeCloseTo(2.776, 3)
    expect(tQuantile(0.975, 9)).toBeCloseTo(2.262, 3)
    expect(tQuantile(0.975, 19)).toBeCloseTo(2.093, 3)
    expect(tQuantile(0.975, 29)).toBeCloseTo(2.045, 3)
    expect(tCDF(0, 7)).toBeCloseTo(0.5, 12)
    expect(tCDF(-2, 7)).toBeCloseTo(1 - tCDF(2, 7), 12)
  })
  it('builds the interval from the differences, with the paired t-test p-value', () => {
    const a = [12, 15, 11, 14, 13], b = [10, 12, 10, 11, 12] // d = 2, 3, 1, 3, 1: mean 2, sd 1
    const ci = pairedTCI(a, b)
    expect(ci.n).toBe(5)
    expect(ci.mean).toBeCloseTo(2, 12)
    const half = 2.776 * (1 / Math.sqrt(5))
    expect(ci.lo).toBeCloseTo(2 - half, 2)
    expect(ci.hi).toBeCloseTo(2 + half, 2)
    expect(ci.p).toBeLessThan(0.05)
    expect(ci.p).toBeCloseTo(0.0111, 3) // t = 4.47 on 4 df (scipy ttest_rel: 0.01106)
  })
  it('sees a consistent per-shift gap that the unpaired test cannot', () => {
    // Shifts vary a lot (cost 100 to 900); strategy B is always exactly 3 points dearer.
    const a = [100, 300, 500, 700, 900], b = a.map((x) => x + 3)
    const paired = pairedTCI(a, b)
    expect(paired.hi).toBeLessThan(0)
    expect(paired.p).toBe(0)
    const unpaired = unpairedTCI(a, b)
    expect(unpaired.lo).toBeLessThan(0)
    expect(unpaired.hi).toBeGreaterThan(0)
    expect(unpaired.p).toBeGreaterThan(0.9)
  })
  it('drops shifts where either run is missing, and gives no interval below two pairs', () => {
    const ci = pairedTCI([1, NaN, 3, 4], [0, 0, NaN, 1])
    expect(ci.n).toBe(2)
    expect(ci.mean).toBeCloseTo(2, 12)
    const none = pairedTCI([1, NaN], [0, 0])
    expect(none.n).toBe(1)
    expect(Number.isNaN(none.lo)).toBe(true)
    expect(Number.isNaN(none.p)).toBe(true)
    expect(Number.isNaN(pairedBootstrapCI([NaN], [1]).mean)).toBe(true)
  })
  it('widens the interval when the level is adjusted', () => {
    const a = [12, 15, 11, 14, 13], b = [10, 12, 10, 11, 12]
    const plain = pairedTCI(a, b), strict = pairedTCI(a, b, { alpha: 0.05 / 6 })
    expect(strict.lo).toBeLessThan(plain.lo)
    expect(strict.hi).toBeGreaterThan(plain.hi)
    expect(strict.lo).toBeLessThan(0) // no longer significant once six comparisons share the 5%
  })
  it('uses t below 30 pairs and the bootstrap from there', () => {
    const a = Array.from({ length: 30 }, (_, i) => 10 + (i % 3)), b = a.map((x, i) => x - 1 + (i % 2) * 0.5)
    expect(pairedCI(a.slice(0, 10), b.slice(0, 10)).method).toBe('t')
    expect(pairedCI(a, b).method).toBe('bootstrap')
    expect(pairedCI(a, b).lo).toBeGreaterThan(0)
  })
})

describe('holm', () => {
  it('steps down through the sorted p-values and stops at the first miss', () => {
    // Sorted: 0.005×4 = 0.02 ✓, 0.01×3 = 0.03 ✓, 0.03×2 = 0.06 ✗, then 0.04 is not tested.
    const out = holm([0.01, 0.04, 0.03, 0.005])
    expect(out.m).toBe(4)
    expect(out.reject).toEqual([true, false, false, true])
    expect(out.adjusted.map((p) => Math.round(p * 1000) / 1000)).toEqual([0.03, 0.06, 0.06, 0.02])
    expect(out.level.map((l) => Math.round(l * 10000) / 10000)).toEqual([0.0167, 0.025, 0.025, 0.0125])
  })
  it('rejects nothing when every comparison is noise, and ignores missing ones', () => {
    const out = holm([0.3, NaN, 0.04, 0.2])
    expect(out.m).toBe(3)
    expect(out.reject).toEqual([false, false, false, false])
    expect(Number.isNaN(out.adjusted[1])).toBe(true)
    expect(out.level[2]).toBeCloseTo(0.05 / 3, 12) // 0.04 > 0.0167: the first miss
  })
  it('is a plain 5% test for a single comparison', () => {
    expect(holm([0.04])).toMatchObject({ reject: [true], level: [0.05], m: 1 })
  })
})

const r = (algorithm, objective, runtime_ms, crit = 100, pri = 100) => ({
  algorithm, label: algorithm, assignments: [], unassigned: [], routes: [],
  metrics: { objective, runtime_ms, critical_coverage_pct: crit, priority_weighted_coverage_pct: pri,
    assigned: 10, jobs: 10, coverage_pct: 100, mean_response_min: 5, wait_min_total: 0 },
})

describe('best-value recommendation', () => {
  it('takes the faster plan when the cost gap is inside the noise margin', () => {
    const rec = recommend([r('alns', 505, 300), r('pyvrp', 500, 1100)], 'value')
    expect(rec.winner.algorithm).toBe('alns')
    expect(rec.why).toMatch(/noise margin/)
  })
  it('pays for latency when the saving is real', () => {
    const rec = recommend([r('alns', 600, 300), r('pyvrp', 500, 1100)], 'value')
    expect(rec.winner.algorithm).toBe('pyvrp')
  })
  it('never trades away bottleneck coverage for cost or speed', () => {
    const rec = recommend([r('greedy', 300, 1, 90), r('pyvrp', 500, 1100, 100)], 'value')
    expect(rec.winner.algorithm).toBe('pyvrp')
    expect(rec.tradeoff.join(' ')).toMatch(/Not considered/)
  })
  it('finds the cost × latency frontier', () => {
    const front = paretoFront([r('a', 500, 1000), r('b', 600, 10), r('c', 700, 2000)]).map((x) => x.algorithm)
    expect(front).toEqual(['a', 'b'])
  })
})
