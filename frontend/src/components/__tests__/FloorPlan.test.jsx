import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FloorPlan from '../FloorPlan.jsx'
import { areasOf, setActiveFab } from '../../lib/fab.js'
import { fixtures } from '../../test/api.js'

const { scenario, plans, fab1 } = fixtures

function renderFloor(props = {}) {
  const onSelect = vi.fn()
  render(<FloorPlan scenario={scenario} result={plans.pyvrp} baseline={plans.greedy} areas={areasOf(fab1)}
    selection={null} onSelect={onSelect} offShift={new Set()} showChanges {...props} />)
  return { onSelect }
}

beforeEach(() => setActiveFab(fab1))

describe('FloorPlan', () => {
  it('draws every job and engineer as a labelled, focusable control', () => {
    renderFloor()
    expect(screen.getByRole('img', { name: `Fab floor plan, ${plans.pyvrp.label}` })).toBeInTheDocument()
    const jobs = screen.getAllByRole('button', { name: /^J\d+,/ })
    const engineers = screen.getAllByRole('button', { name: /^Engineer / })
    expect(jobs).toHaveLength(scenario.jobs.length)
    expect(engineers).toHaveLength(scenario.engineers.length)
    expect([...jobs, ...engineers].every((el) => el.getAttribute('tabindex') === '0')).toBe(true)
  })

  it('says who each job is assigned to, or that it is unassigned', () => {
    renderFloor()
    const served = plans.pyvrp.assignments[0]
    expect(screen.getByRole('button', { name: new RegExp(`^${served.job_id},.*assigned to ${served.tech_id}$`) })).toBeInTheDocument()
    const unserved = plans.pyvrp.unassigned[0].job_id
    expect(screen.getByRole('button', { name: new RegExp(`^${unserved},.*unassigned$`) })).toBeInTheDocument()
  })

  it('labels each tool area from the fab profile', () => {
    renderFloor()
    for (const f of fab1.families) expect(screen.getByText(f.label.toUpperCase())).toBeInTheDocument()
  })

  it('selects a job or engineer by click or keyboard', async () => {
    const user = userEvent.setup()
    const { onSelect } = renderFloor()
    await user.click(screen.getByRole('button', { name: /^J006,/ }))
    expect(onSelect).toHaveBeenLastCalledWith({ type: 'job', id: 'J006' })
    screen.getByRole('button', { name: /^Engineer E02,/ }).focus()
    await user.keyboard('{Enter}')
    expect(onSelect).toHaveBeenLastCalledWith({ type: 'engineer', id: 'E02' })
  })

  it('flags jobs whose coverage differs from the Greedy baseline', () => {
    const { container } = render(<FloorPlan scenario={scenario} result={plans.pyvrp} baseline={plans.greedy}
      areas={areasOf(fab1)} selection={null} offShift={new Set()} showChanges />)
    const greedyServed = new Set(plans.greedy.assignments.map((a) => a.job_id))
    const pyvrpServed = new Set(plans.pyvrp.assignments.map((a) => a.job_id))
    const expected = scenario.jobs.filter((j) => greedyServed.has(j.id) !== pyvrpServed.has(j.id)).length
    expect(expected).toBeGreaterThan(0)
    expect(container.querySelectorAll('.f-job.changed')).toHaveLength(expected)
  })

  it('marks the selected job as pressed', () => {
    renderFloor({ selection: { type: 'job', id: 'J006' } })
    expect(screen.getByRole('button', { name: /^J006,/ })).toHaveAttribute('aria-pressed', 'true')
  })
})
