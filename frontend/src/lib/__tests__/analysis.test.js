import { beforeEach, describe, expect, it } from 'vitest'
import { disagreements, insights, rankBy, recommend, speedup } from '../analysis.js'
import { improvement } from '../metrics.js'
import { clock, fmt, plural } from '../format.js'
import { setActiveFab } from '../fab.js'
import { fixtures } from '../../test/api.js'

const metrics = (o) => ({
  jobs: 4, assigned: 4, coverage_pct: 100, critical_coverage_pct: 100, priority_weighted_coverage_pct: 100,
  mean_response_min: 10, walk_m_per_job: 90, wait_min_total: 100, overqualification_levels: 2,
  utilization_pct: 40, workload_std: 1, objective: 500, runtime_ms: 1, ...o,
})
const result = (algorithm, m, assignments, unassigned = []) =>
  ({ algorithm, label: algorithm, metrics: metrics(m), assignments, unassigned, routes: [] })
const a = (job_id, tech_id) => ({ job_id, tech_id })
const jobs = ['J1', 'J2', 'J3', 'J4'].map((id, i) => ({ id, priority: i === 0 ? 3 : 1, skill: 'etch', tool: 'T' }))

const greedy = result('greedy', { assigned: 3, coverage_pct: 75, objective: 800, mean_response_min: 20 },
  [a('J1', 'E1'), a('J2', 'E1'), a('J3', 'E2')], [{ job_id: 'J4' }])
const hungarian = result('hungarian', { objective: 700, mean_response_min: 5, wait_min_total: 300 },
  [a('J1', 'E2'), a('J2', 'E1'), a('J3', 'E2'), a('J4', 'E1')])
const pyvrp = result('pyvrp', { objective: 400, mean_response_min: 12 },
  [a('J1', 'E1'), a('J2', 'E1'), a('J3', 'E2'), a('J4', 'E2')])

describe('recommend', () => {
  it('picks the lowest total cost for the cost goal and states the margin', () => {
    const r = recommend([greedy, hungarian, pyvrp], 'cost')
    expect(r.winner.algorithm).toBe('pyvrp')
    expect(r.why).toContain('300')
  })
  it('breaks a tie on the lead metric with the next one', () => {
    const r = recommend([greedy, hungarian, pyvrp], 'bottleneck')
    // all cover 100% of bottleneck downs; hungarian responds fastest
    expect(r.winner.algorithm).toBe('hungarian')
  })
  it('reports what the winner gives up', () => {
    const r = recommend([greedy, hungarian, pyvrp], 'cost')
    expect(r.tradeoff.join(' ')).toMatch(/Hungarian/)
  })
})

describe('disagreements', () => {
  it('lists jobs where strategies differ, coverage differences first', () => {
    const d = disagreements([greedy, hungarian, pyvrp], jobs)
    expect(d[0].job.id).toBe('J4')
    expect(d[0].coverageDiffers).toBe(true)
    expect(d.map((x) => x.job.id)).toContain('J1')
    expect(d.map((x) => x.job.id)).not.toContain('J2')
  })
})

describe('insights', () => {
  it('names jobs greedy strands that a batch method serves', () => {
    const notes = insights([greedy, hungarian, pyvrp], { jobs })
    expect(notes[0].jobs).toEqual(['J4'])
  })
})

describe('helpers', () => {
  it('improvement is positive when a metric gets better in either direction', () => {
    expect(improvement('coverage_pct', 90, 80)).toBe(10)
    expect(improvement('objective', 400, 500)).toBe(100)
  })
  it('formats shift-relative minutes as wall-clock time from 07:00', () => {
    expect(clock(0)).toBe('07:00')
    expect(clock(725)).toBe('19:05')
    expect(fmt(3.14159)).toBe('3.1')
  })
  it('agrees nouns with counts', () => {
    expect(plural(1, 'job')).toBe('1 job')
    expect(plural(3, 'job')).toBe('3 jobs')
    expect(plural(5, 'strategy', 'strategies')).toBe('5 strategies')
  })
})

// ---------------------------------------------------------------- review fixes
const plan = (algorithm, m = {}, assignments = [], unassigned = []) => result(algorithm, m, assignments, unassigned)
const permutations = (xs) => (xs.length <= 1 ? [xs] : xs.flatMap((x, i) => permutations([...xs.slice(0, i), ...xs.slice(i + 1)]).map((p) => [x, ...p])))

describe('best value: coverage guard', () => {
  it('keeps the bottleneck guard when no plan is best on both coverage measures', () => {
    // Greedy serves the most priority work but fewer bottleneck downs; nobody leads on both.
    const rs = [
      plan('greedy', { critical_coverage_pct: 90, priority_weighted_coverage_pct: 95, objective: 200, runtime_ms: 1 }),
      plan('hungarian', { critical_coverage_pct: 100, priority_weighted_coverage_pct: 80, objective: 500, runtime_ms: 3 }),
      plan('pyvrp', { critical_coverage_pct: 100, priority_weighted_coverage_pct: 82, objective: 400, runtime_ms: 300 }),
    ]
    const rec = recommend(rs, 'value')
    expect(rec.winner.algorithm).toBe('pyvrp')
    expect(rec.pool).toEqual(['hungarian', 'pyvrp'])
    expect(rec.why).toMatch(/bottleneck coverage alone/)
    expect(rec.tradeoff.join(' ')).toMatch(/Not considered.*Greedy/)
  })
})

describe('best value: wording', () => {
  it('never calls a win "by a real margin" when the runner-up is inside the noise margin', () => {
    const rs = [plan('regret', { objective: 555.4, runtime_ms: 6 }), plan('alns', { objective: 563.4, runtime_ms: 180 }), plan('pyvrp', { objective: 555.4, runtime_ms: 390 })]
    const rec = recommend(rs, 'value')
    expect(rec.winner.algorithm).toBe('regret')
    expect(rec.why).not.toMatch(/real margin|worth its|(^|[^\d.,])0 pts/)
    expect(rec.why).toMatch(/fastest of 3 equivalent plans/)
    expect(rec.why).toMatch(/30× faster than ALNS \(6 ms vs 180 ms\)/)
  })
  it('does not say the fastest plan is "worth its" solve time', () => {
    const rec = recommend([plan('alns', { objective: 600, runtime_ms: 300 }), plan('pyvrp', { objective: 400, runtime_ms: 1 })], 'value')
    expect(rec.why).toMatch(/real margin/)
    expect(rec.why).toMatch(/also the fastest/)
    expect(rec.why).not.toMatch(/worth its/)
  })
  it('says a slower cheapest plan is worth its solve when the saving is real', () => {
    const rec = recommend([plan('greedy', { objective: 600, runtime_ms: 2 }), plan('pyvrp', { objective: 400, runtime_ms: 1100 })], 'value')
    expect(rec.why).toMatch(/worth its 1,100 ms solve/)
    expect(rec.tradeoff.join(' ')).toMatch(/Greedy answers in 2 ms but costs 200 pts more/)
  })
  it('handles equal costs and near-equal solve times without rounding nonsense', () => {
    const rec = recommend([plan('greedy', { objective: 500, runtime_ms: 3 }), plan('hungarian', { objective: 500, runtime_ms: 2 })], 'value')
    expect(rec.winner.algorithm).toBe('hungarian')
    expect(rec.why).toMatch(/Hungarian and Greedy cost the same \(500 pts\)/)
    expect(rec.why).not.toMatch(/(^|[^\d.,])0 pts|×/)
    expect(rec.why).toMatch(/2 ms vs 3 ms/)
  })
  it('reports the actual bottleneck coverage, not "full"', () => {
    const rs = [plan('greedy', { critical_coverage_pct: 50, objective: 100 }), plan('pyvrp', { critical_coverage_pct: 75, objective: 300 })]
    expect(recommend(rs, 'value').why).toMatch(/best bottleneck coverage \(75% of bottleneck downs\)/)
  })
  it('agrees the noun with the count', () => {
    const rec = recommend([plan('pyvrp', { jobs: 1, assigned: 1 })], 'value')
    expect(rec.why).toMatch(/Covers 1 of 1 job,/)
  })
})

describe('speedup', () => {
  it('words a speed difference so rounding never claims what the numbers do not show', () => {
    expect(speedup(2, 3)).toBeNull()
    expect(speedup(100, 110)).toBeNull()
    expect(speedup(100, 140)).toBe('40 ms faster')
    expect(speedup(180, 390)).toBe('2.2× faster')
    expect(speedup(6, 390)).toBe('65× faster')
  })
})

describe('provisional recommendation', () => {
  it('holds comparative claims while strategies are still solving', () => {
    const rec = recommend([plan('greedy')], 'value', { complete: false, waiting: ['hungarian', 'regret', 'alns', 'pyvrp'] })
    expect(rec.provisional).toBe(true)
    expect(rec.why).toMatch(/^Provisional: best of the 1 strategy solved so far\. Waiting for Hungarian, Regret-2, ALNS and PyVRP/)
    expect(rec.why).not.toMatch(/Only strategy/)
    expect(rec.tradeoff).toEqual([])
  })
  it('says when the plans on screen predate the weights', () => {
    const rec = recommend([greedy, pyvrp], 'cost', { complete: false, stale: true })
    expect(rec.why).toMatch(/previous weights/)
  })
  it('is final once every strategy has answered', () => {
    expect(recommend([greedy, pyvrp], 'value').provisional).toBe(false)
  })
})

describe('goal ranking', () => {
  it('ranks the same way whatever order the results arrive in', () => {
    // Response 10.0 ~ 10.2 ~ 10.4 pairwise within tolerance, but 10.0 and 10.4 are not: a
    // pairwise-tie comparator isn't transitive. Anchoring on the best one is.
    const rs = [
      plan('greedy', { mean_response_min: 10.2, priority_weighted_coverage_pct: 90 }),
      plan('hungarian', { mean_response_min: 10.4, priority_weighted_coverage_pct: 99 }),
      plan('pyvrp', { mean_response_min: 10.0, priority_weighted_coverage_pct: 80 }),
    ]
    const orders = permutations(rs).map((p) => recommend(p, 'bottleneck').ranked.map((r) => r.algorithm).join())
    expect(new Set(orders).size).toBe(1)
    expect(orders[0]).toBe('greedy,pyvrp,hungarian')
    expect(rankBy(rs, ['mean_response_min']).map((r) => r.algorithm)).toEqual(['greedy', 'pyvrp', 'hungarian'])
  })
  it('explains a tie-break with both values', () => {
    const rs = [plan('greedy', { mean_response_min: 20 }), plan('hungarian', { mean_response_min: 5 }), plan('pyvrp', { mean_response_min: 12 })]
    expect(recommend(rs, 'bottleneck').why).toMatch(/^Ties with Greedy and PyVRP on bottleneck downs covered \(100%\) and wins on response to tool-downs: 5 min vs 12 min for PyVRP\./)
  })
  it('counts the strategies that actually tie', () => {
    const rs = ['greedy', 'hungarian', 'regret', 'alns', 'pyvrp'].map((x) => plan(x))
    expect(recommend(rs, 'bottleneck').why).toMatch(/^All 5 strategies tie on this goal/)
    expect(recommend(rs.slice(0, 2), 'cost').why).toMatch(/^All 2 strategies tie/)
  })
})

describe('findings', () => {
  beforeEach(() => setActiveFab(fixtures.fab1))
  const four = ['J1', 'J2', 'J3', 'J4'].map((id) => ({ id, priority: 2, kind: 'down', skill: 'etch', tool: 'T' }))

  it('counts agreement only over jobs some strategy serves, with plurals that agree', () => {
    const x = plan('hungarian', {}, [a('J1', 'E1'), a('J2', 'E1'), a('J3', 'E2')], [{ job_id: 'J4' }])
    const y = plan('regret', {}, [a('J1', 'E1'), a('J2', 'E2')], [{ job_id: 'J3' }, { job_id: 'J4' }])
    const agree = insights([x, y], { jobs: four }).find((n) => n.icon === '≡')
    expect(agree.text).toMatch(/^1 job is served by some strategies and not others\./)
    // J4 is served by nobody, so it isn't a case of "the same engineer". J1 is; J2 isn't; J3 is half-served.
    expect(agree.text).toMatch(/Of the 3 jobs at least one strategy serves, all 2 send the same engineer to 1 \(33%\)/)
  })

  it('names tool families by their labels', () => {
    const x = plan('greedy', {}, [a('J1', 'E1')], [{ job_id: 'J2' }])
    const y = plan('pyvrp', {}, [a('J1', 'E2')], [{ job_id: 'J2' }])
    const jobs2 = [{ id: 'J1', priority: 1, skill: 'litho', kind: 'pm' }, { id: 'J2', priority: 3, skill: 'etch', kind: 'down' }]
    const gap = insights([x, y], { jobs: jobs2 }).find((n) => n.icon === '!')
    expect(gap.text).toMatch(/^1 job served by no strategy \(1 Etch\)/)
    expect(gap.parts[0]).toEqual({ b: '1 job served by no strategy' })
  })

  it('only credits idle wait for a saving when wait is most of it', () => {
    const w = { travel_100m: 4, wait_min: 0.2, overqualification: 8, workload_balance: 5, priority_reward: 60 }
    const walkDriven = [
      plan('regret', { objective: 900, walk_m_total: 9000, wait_min_total: 100 }),
      plan('pyvrp', { objective: 600, walk_m_total: 2000, wait_min_total: 150 }),
    ]
    const n = insights(walkDriven, { jobs: four }, { weights: w }).find((x) => x.icon === '↘')
    expect(n.text).toMatch(/mostly by cutting walking \(2,000 vs 9,000 m\)/)
    expect(n.text).not.toMatch(/idle wait/)
    const waitDriven = [
      plan('regret', { objective: 900, walk_m_total: 2000, wait_min_total: 1600 }),
      plan('pyvrp', { objective: 600, walk_m_total: 2000, wait_min_total: 100 }),
    ]
    expect(insights(waitDriven, { jobs: four }, { weights: w }).find((x) => x.icon === '↘').text).toMatch(/mostly by cutting idle wait \(100 vs 1,600 min\)/)
    // Without the weights, only the direction is checked.
    expect(insights(walkDriven, { jobs: four }).find((x) => x.icon === '↘').text).not.toMatch(/idle wait/)
  })

  it('only says Hungarian spreads work evenly when its workload spread is lower', () => {
    const notes = (hStd) => insights([
      plan('hungarian', { wait_min_total: 400, workload_std: hStd }),
      plan('regret', { wait_min_total: 100, workload_std: 1 }),
    ], { jobs: four })
    expect(notes(0.5).find((n) => n.icon === '◷').text).toMatch(/^Hungarian spreads work more evenly .* but adds 300 min of idle wait/)
    const uneven = notes(2).find((n) => n.icon === '◷').text
    expect(uneven).toMatch(/^Hungarian adds 300 min of idle wait over Regret-2/)
    expect(uneven).not.toMatch(/evenly/)
  })

  it('compares response times only between plans that serve tool-downs', () => {
    const none = plan('greedy', { mean_response_min: 0 }, [], four.map((j) => ({ job_id: j.id })))
    const some = plan('pyvrp', { mean_response_min: 12 }, [a('J1', 'E1')])
    const slow = plan('alns', { mean_response_min: 30 }, [a('J1', 'E2')])
    const resp = insights([none, some, slow], { jobs: four }).find((n) => n.icon === '⏱')
    expect(resp.text).toMatch(/^PyVRP reaches tool-downs fastest: 12 min on average over the tool-downs it serves, against 30 min for ALNS/)
  })
})
