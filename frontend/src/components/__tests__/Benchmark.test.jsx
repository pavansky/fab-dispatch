import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import Benchmark from '../Benchmark.jsx'
import { setActiveFab } from '../../lib/fab.js'
import { fixtures, mockApi } from '../../test/api.js'

const { fab1, meta } = fixtures
const profile = { ...fab1, presets: { normal: fab1.presets.normal } }
const base = [500, 510, 490, 505, 495]
const noise = [2, -3, 1, -1, 2] // mean +0.2: indistinguishable from 0 over five shifts

/** Benchmark runs: { algo: [cost offsets per seed, runtime ms] }. */
function runs(spec) {
  return Object.entries(spec).flatMap(([algorithm, [offsets, runtime]]) => base.map((c, i) => ({
    preset: 'normal', seed: i + 1, algorithm,
    metrics: { objective: c + (Array.isArray(offsets) ? offsets[i] : offsets), runtime_ms: runtime, coverage_pct: 100, critical_coverage_pct: 100, mean_response_min: 10, wait_min_total: 100, workload_std: 1 },
  })))
}

async function bench(spec) {
  mockApi({ 'POST /benchmark': { runs: runs(spec) } })
  render(<Benchmark profile={profile} weights={meta.default_weights} size={{ n_engineers: 14, n_jobs: 45 }} canDispatch />)
  await userEvent.click(screen.getByRole('button', { name: 'Run benchmark' }))
  return (await screen.findByText(/^Best value:/)).closest('p')
}

beforeEach(() => setActiveFab(fab1))

describe('Benchmark verdicts', () => {
  it('calls a fast plan "not significantly costlier", not "equivalent"', async () => {
    const p = await bench({ greedy: [100, 2], regret: [noise, 6], pyvrp: [0, 400] })
    expect(p).toHaveTextContent('Best value: Regret-2.')
    expect(p).toHaveTextContent(/PyVRP has the lowest mean cost, but Regret-2 is not significantly costlier at n = 5 shifts/)
    expect(p).toHaveTextContent(/not proof they are equivalent/)
    expect(p).toHaveTextContent(/67× faster \(6 ms vs 400 ms\)/)
    expect(p).not.toHaveTextContent(/isn't a real difference/)
  })

  it('names the strategies tied with a cheapest plan that is also the fastest', async () => {
    const p = await bench({ regret: [0, 6], pyvrp: [noise, 400], greedy: [100, 2] })
    expect(p).toHaveTextContent('Best value: Regret-2.')
    expect(p).toHaveTextContent(/also the fastest of the strategies not significantly different from it at n = 5 shifts \(PyVRP\)/)
    expect(p).not.toHaveTextContent(/nothing else is statistically tied/)
  })

  it('says every other strategy is significantly costlier only when that is so', async () => {
    const p = await bench({ pyvrp: [0, 400], greedy: [100, 2] })
    expect(p).toHaveTextContent(/every other strategy is significantly costlier at n = 5 shifts/)
  })

  it('labels the whiskers as unpaired and the verdicts as paired', async () => {
    await bench({ pyvrp: [0, 400], greedy: [100, 2] })
    expect(screen.getByText(/Whiskers: 95% bootstrap CI of each strategy's own mean cost \(unpaired\)/)).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /paired 95% CI/ })).toBeInTheDocument()
    expect(screen.getByText('Significantly costlier')).toBeInTheDocument()
  })
})
