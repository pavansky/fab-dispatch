import { describe, expect, it } from 'vitest'
import { pairedBootstrapCI } from '../stats.js'
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
