import { describe, expect, it } from 'vitest'
import { disagreements, insights, recommend } from '../analysis.js'
import { improvement } from '../metrics.js'
import { clock, fmt } from '../format.js'

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
  it('picks the lowest operating cost for the cost goal and states the margin', () => {
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
})
