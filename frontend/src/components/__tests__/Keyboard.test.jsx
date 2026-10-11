// Everything clickable is also reachable and operable from the keyboard (Enter and Space).
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MetricBars from '../MetricBars.jsx'
import Inspector from '../Inspector.jsx'
import Schedule from '../Schedule.jsx'
import Workforce from '../Workforce.jsx'
import { setActiveFab } from '../../lib/fab.js'
import { ALGO_ORDER } from '../../lib/metrics.js'
import { fixtures, mockApi } from '../../test/api.js'

const { scenario, plans, fab1 } = fixtures
const results = ALGO_ORDER.map((a) => plans[a])

beforeEach(() => {
  setActiveFab(fab1)
  mockApi({ 'POST /repairs/similar': { neighbours: [], prediction: null } })
})

describe('keyboard access', () => {
  it('metric bars open a strategy with Enter or Space, and are inert without a handler', async () => {
    const onPick = vi.fn()
    const { unmount } = render(<MetricBars results={results} keys={['objective']} onPick={onPick} />)
    const bar = screen.getByRole('button', { name: /^Hungarian, Total cost \(objective\): .* Open on the floor plan$/ })
    bar.focus()
    await userEvent.keyboard('{Enter}')
    await userEvent.keyboard(' ')
    expect(onPick).toHaveBeenCalledTimes(2)
    expect(onPick).toHaveBeenLastCalledWith('hungarian')
    unmount()
    render(<MetricBars results={results} keys={['objective']} />)
    expect(screen.queryAllByRole('button')).toHaveLength(0)
  })

  it("reaches a route's stops in the inspector", async () => {
    const route = plans.pyvrp.routes.find((r) => r.stops.length > 1)
    const onSelect = vi.fn()
    render(<Inspector selection={{ type: 'engineer', id: route.tech_id }} scenario={scenario} results={results} active="pyvrp"
      offShift={new Set()} onSelect={onSelect} onToggleEngineer={vi.fn()} />)
    screen.getByRole('button', { name: `Inspect ${route.stops[1].job_id}` }).focus()
    await userEvent.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledOnce()
    expect(onSelect).toHaveBeenCalledWith({ type: 'job', id: route.stops[1].job_id })
  })

  it('reaches an engineer from the schedule', async () => {
    const onSelect = vi.fn()
    const eng = scenario.engineers[2]
    render(<Schedule scenario={scenario} result={plans.pyvrp} selection={null} onSelect={onSelect} offShift={new Set()} />)
    screen.getByRole('button', { name: `Inspect ${eng.id} ${eng.name}` }).focus()
    await userEvent.keyboard(' ')
    expect(onSelect).toHaveBeenCalledWith({ type: 'engineer', id: eng.id })
  })

  it('reaches an engineer from the certification matrix', async () => {
    const onSelect = vi.fn()
    const eng = scenario.engineers[0]
    render(<Workforce scenario={scenario} result={plans.pyvrp} offShift={new Set()} onSelect={onSelect} />)
    screen.getByRole('button', { name: `Inspect ${eng.id} ${eng.name}` }).focus()
    await userEvent.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledWith({ type: 'engineer', id: eng.id })
  })
})
