// Metrics the API may leave out (older responses) or report as null (nothing to measure):
// every renderer says "n/a" or why, and never shows NaN.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import MetricBars from '../MetricBars.jsx'
import Overview from '../Overview.jsx'
import Benchmark from '../Benchmark.jsx'
import { GOALS, insights, recommend } from '../../lib/analysis.js'
import { ALGO_ORDER, bestOf, improvement, workloadKey } from '../../lib/metrics.js'
import { fmt } from '../../lib/format.js'
import { setActiveFab } from '../../lib/fab.js'
import { fixtures, mockApi } from '../../test/api.js'

const { scenario, plans, fab1, meta } = fixtures
// The fixture plans predate the new keys: no workload_minutes_std, response_p95_min, unserved_downs.
const oldKeys = ALGO_ORDER.map((a) => plans[a])
// A shift without bottleneck downs: critical_coverage_pct is null, and the new keys are present.
const noDowns = ALGO_ORDER.map((a, i) => ({
  ...plans[a],
  metrics: { ...plans[a].metrics, critical_coverage_pct: null, critical_jobs: 0, unserved_downs: i, response_p95_min: 30 + i, workload_minutes_std: 42.5 + i },
}))
const noDownsScenario = { ...scenario, jobs: scenario.jobs.map((j) => (j.priority === 3 ? { ...j, priority: 2 } : j)) }

beforeEach(() => setActiveFab(fab1))

describe('metrics without a value', () => {
  it('format and helpers never produce NaN', () => {
    expect(fmt(null)).toBe('n/a')
    expect(fmt(undefined)).toBe('n/a')
    expect(fmt(NaN)).toBe('n/a')
    expect(fmt(1.25)).toBe('1.3')
    expect(Number.isNaN(improvement('coverage_pct', null, 50))).toBe(true)
    expect(bestOf(noDowns, 'critical_coverage_pct')).toBeUndefined()
    expect(bestOf(noDowns, 'unserved_downs')).toBe(0)
    expect(workloadKey(oldKeys)).toBe('workload_std')
    expect(workloadKey(noDowns)).toBe('workload_minutes_std')
  })

  it('recommends for every goal with null bottleneck coverage, saying there were no bottleneck downs', () => {
    for (const goal of Object.keys(GOALS)) {
      const rec = recommend(noDowns, goal)
      expect(rec.winner).toBeTruthy()
      expect(rec.why).not.toMatch(/NaN|n\/a%|–/)
      expect(rec.tradeoff.join(' ')).not.toMatch(/NaN/)
    }
    expect(recommend(noDowns, 'value').why).toMatch(/no bottleneck downs this shift/)
    expect(recommend(noDowns, 'bottleneck').why).toMatch(/no bottleneck downs/)
    const notes = insights(noDowns, noDownsScenario, { weights: meta.default_weights })
    expect(notes.map((n) => n.text).join(' ')).not.toMatch(/NaN|n\/a/)
  })

  it('still works for plans that lack the new keys entirely', () => {
    for (const goal of Object.keys(GOALS)) expect(recommend(oldKeys, goal).why).not.toMatch(/NaN|n\/a/)
    const { container } = render(<MetricBars results={oldKeys} keys={[workloadKey(oldKeys), 'critical_coverage_pct']} />)
    expect(screen.getByRole('heading', { name: /Workload spread \(std\)/ })).toBeInTheDocument()
    expect(container.textContent).not.toMatch(/NaN|n\/a/)
  })

  it('shows "no bottleneck downs" in metric bars and the workload spread in minutes', () => {
    const { container } = render(<MetricBars results={noDowns} keys={['critical_coverage_pct', workloadKey(noDowns), 'unserved_downs']} onPick={() => {}} />)
    expect(container.textContent).not.toMatch(/NaN/)
    expect(screen.getByRole('heading', { name: /Workload spread \(min\)/ })).toBeInTheDocument()
    expect(screen.getAllByText('no bottleneck downs')).toHaveLength(ALGO_ORDER.length)
    expect(screen.getByRole('button', { name: /^Greedy, Bottleneck downs covered: no bottleneck downs\./ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Greedy, Workload spread \(min\): 42\.5 min\./ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Greedy, Tool-downs left unserved: 0\./ })).toBeInTheDocument()
  })

  it('renders the overview scorecards and bars with nulls and without NaN', () => {
    const reco = recommend(noDowns, 'value')
    const { container } = render(<Overview results={noDowns} pending={new Set()} reco={reco} scenario={noDownsScenario} weights={meta.default_weights}
      goal="value" onGoal={() => {}} onPickAlgo={() => {}} onSelect={() => {}} />)
    expect(container.textContent).not.toMatch(/NaN/)
    const card = screen.getAllByRole('button', { name: 'View on floor plan' })[0].closest('section')
    expect(within(card).getAllByText('no bottleneck downs').length).toBeGreaterThan(0)
    expect(screen.getByRole('heading', { name: /Workload spread \(min\)/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Response to tool-downs, p95/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Tool-downs left unserved/ })).toBeInTheDocument()
  })

  it('benchmarks a preset with no bottleneck downs as "no bottleneck downs", not NaN', async () => {
    const runs = [1, 2, 3, 4, 5].flatMap((seed) => ['greedy', 'pyvrp'].map((algorithm) => ({
      preset: 'normal', seed, algorithm,
      metrics: { objective: algorithm === 'greedy' ? 600 + seed : 500 + seed, runtime_ms: algorithm === 'greedy' ? 2 : 300, coverage_pct: 100, critical_coverage_pct: null,
        mean_response_min: null, wait_min_total: 100, workload_minutes_std: 12, unserved_downs: 0, response_p95_min: null },
    })))
    mockApi({ 'POST /benchmark': { runs } })
    const { container } = render(<Benchmark profile={{ ...fab1, presets: { normal: fab1.presets.normal } }} weights={meta.default_weights} size={{ n_engineers: 14, n_jobs: 45 }} canDispatch />)
    await userEvent.click(screen.getByRole('button', { name: 'Run benchmark' }))
    await screen.findByText(/^Best value:/)
    expect(container.textContent).not.toMatch(/NaN/)
    const table = document.querySelector('.bench-table')
    expect(within(table).getAllByText('no bottleneck downs')).toHaveLength(2)
    expect(within(table).getAllByText('no tool-downs served')).toHaveLength(2)
    expect(within(table).getByRole('columnheader', { name: /Workload min/ })).toBeInTheDocument()
    expect(screen.getByText('Significantly costlier')).toBeInTheDocument()
  })
})
