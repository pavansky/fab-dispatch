import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Inspector from '../Inspector.jsx'
import { setActiveFab } from '../../lib/fab.js'
import { ALGO_ORDER } from '../../lib/metrics.js'
import { fixtures, mockApi } from '../../test/api.js'

const { scenario, plans, fab1 } = fixtures
const results = ALGO_ORDER.map((a) => plans[a])

function renderInspector(selection, props = {}) {
  const handlers = { onSelect: vi.fn(), onToggleEngineer: vi.fn() }
  render(<Inspector selection={selection} scenario={scenario} results={results} active="pyvrp"
    offShift={new Set()} {...handlers} {...props} />)
  return handlers
}

beforeEach(() => {
  setActiveFab(fab1)
  mockApi({ 'POST /repairs/similar': { neighbours: [], prediction: null } })
})

describe('Inspector', () => {
  it('invites a selection when nothing is selected', () => {
    renderInspector(null)
    expect(screen.getByText('Select a job or engineer')).toBeInTheDocument()
  })

  it('shows what the job needs and its start window', () => {
    renderInspector({ type: 'job', id: 'J006' })
    const job = scenario.jobs.find((j) => j.id === 'J006')
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent(`J006 ${job.tool}`)
    expect(screen.getByText(new RegExp(`level ${job.min_level}\\+`))).toBeInTheDocument()
    expect(screen.getByText(`${job.duration} min`)).toBeInTheDocument()
  })

  it('explains the decision of every strategy, including the cost breakdown', () => {
    renderInspector({ type: 'job', id: 'J006' })
    const pyvrp = plans.pyvrp.assignments.find((a) => a.job_id === 'J006')
    const block = screen.getByText(pyvrp.explanation).closest('.decision')
    expect(within(block).getByRole('button', { name: `${pyvrp.tech_id} →` })).toBeInTheDocument()
    for (const [k, v] of Object.entries(pyvrp.cost_breakdown)) {
      expect(within(block).getByText(new RegExp(`^${k} ${v > 0 ? '\\+' : ''}`))).toBeInTheDocument()
    }
    expect(document.querySelectorAll('.decision')).toHaveLength(ALGO_ORDER.length)
  })

  it('says why a strategy left the job unserved, with counted rejection reasons', () => {
    renderInspector({ type: 'job', id: 'J006' })
    const greedy = plans.greedy.unassigned.find((u) => u.job_id === 'J006')
    const block = screen.getByText(greedy.reason).closest('.decision')
    expect(within(block).getByText('Unassigned')).toBeInTheDocument()
    expect(within(block).getByText(`${greedy.rejections.skill_missing}× not certified`)).toBeInTheDocument()
    expect(within(block).getByText(`${greedy.rejections.at_capacity}× at max jobs`)).toBeInTheDocument()
  })

  it('jumps from a decision to the engineer who got the job', async () => {
    const { onSelect } = renderInspector({ type: 'job', id: 'J006' })
    const tech = plans.pyvrp.assignments.find((a) => a.job_id === 'J006').tech_id
    await userEvent.click(screen.getAllByRole('button', { name: `${tech} →` })[0])
    expect(onSelect).toHaveBeenCalledWith({ type: 'engineer', id: tech })
  })

  it("shows an engineer's route in order and lets you take them off shift", async () => {
    const route = plans.pyvrp.routes.find((r) => r.stops.length > 1)
    const { onToggleEngineer, onSelect } = renderInspector({ type: 'engineer', id: route.tech_id })
    const stops = screen.getAllByRole('listitem')
    expect(stops.map((li) => li.querySelector('b').textContent)).toEqual(route.stops.map((s) => s.job_id))
    await userEvent.click(stops[1])
    expect(onSelect).toHaveBeenCalledWith({ type: 'job', id: route.stops[1].job_id })
    await userEvent.click(screen.getByRole('button', { name: 'Take off shift (what-if)' }))
    expect(onToggleEngineer).toHaveBeenCalledWith(route.tech_id)
  })

  it('marks an engineer who is off shift', () => {
    const id = scenario.engineers[0].id
    renderInspector({ type: 'engineer', id }, { offShift: new Set([id]) })
    expect(screen.getByText('Off shift')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Bring back on shift' })).toBeInTheDocument()
  })
})
