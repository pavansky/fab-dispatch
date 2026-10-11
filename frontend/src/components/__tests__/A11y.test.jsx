// Screen-reader and keyboard details: one polite live region, tooltips that work on focus
// and describe their trigger, decorative SVG text hidden, thumbnails not in the tab order.
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FloorPlan from '../FloorPlan.jsx'
import Schedule from '../Schedule.jsx'
import LiveShift from '../LiveShift.jsx'
import { AuthProvider, useAuth } from '../../auth.jsx'
import { setActiveFab, areasOf } from '../../lib/fab.js'
import { fixtures, liveRoutes, mockApi, workspaceRoutes } from '../../test/api.js'
import { FakeEventSource } from '../../test/app.jsx'

const { scenario, plans, fab1 } = fixtures
const result = plans.pyvrp
const areas = areasOf(fab1)

beforeEach(() => setActiveFab(fab1))

describe('tooltips', () => {
  it('open on focus, describe the focused bar, and close on Escape', async () => {
    render(<Schedule scenario={scenario} result={result} selection={null} onSelect={vi.fn()} offShift={new Set()} />)
    const stop = result.routes.find((r) => r.stops.length).stops[0]
    const bar = screen.getByRole('button', { name: new RegExp(`^${stop.job_id} `) })
    const tooltip = screen.getByRole('tooltip', { hidden: true })
    expect(tooltip).not.toBeVisible()
    expect(bar).not.toHaveAttribute('aria-describedby')
    fireEvent.focus(bar)
    expect(tooltip).toBeVisible()
    expect(tooltip).toHaveTextContent(stop.job_id)
    expect(bar).toHaveAttribute('aria-describedby', tooltip.id)
    expect(bar).toHaveAccessibleDescription(new RegExp(stop.job_id))
    await userEvent.keyboard('{Escape}')
    expect(tooltip).not.toBeVisible()
    fireEvent.focus(bar)
    expect(bar).toHaveAttribute('aria-describedby', tooltip.id)
    fireEvent.blur(bar)
    expect(bar).not.toHaveAttribute('aria-describedby')
    expect(screen.queryAllByRole('status')).toHaveLength(0) // never a live region
  })

  it('describe a floor-plan job on focus too', () => {
    render(<FloorPlan scenario={scenario} result={result} areas={areas} selection={null} onSelect={vi.fn()} offShift={new Set()} />)
    const job = screen.getByRole('button', { name: /^J006,/ })
    fireEvent.focus(job)
    const tooltip = screen.getByRole('tooltip')
    expect(tooltip).toBeVisible()
    expect(job).toHaveAttribute('aria-describedby', tooltip.id)
    expect(job).toHaveAccessibleDescription(/J006/)
  })
})

describe('floor plan semantics', () => {
  it('hides decorative area labels, counts and sequence numbers from assistive tech', () => {
    const { container } = render(<FloorPlan scenario={scenario} result={result} areas={areas} selection={{ type: 'engineer', id: result.routes[0].tech_id }} onSelect={vi.fn()} offShift={new Set()} />)
    for (const sel of ['.f-area-label', '.f-area-sub', '.f-seq', '.f-eng text']) {
      const els = container.querySelectorAll(sel)
      expect(els.length, sel).toBeGreaterThan(0)
      els.forEach((el) => expect(el).toHaveAttribute('aria-hidden', 'true'))
    }
    expect(screen.getAllByRole('button', { name: /^Engineer E/ })).toHaveLength(scenario.engineers.length)
  })

  it('keeps side-by-side thumbnails out of the tab order and names them as thumbnails', () => {
    const { container } = render(<FloorPlan compact scenario={scenario} result={result} areas={areas} selection={null} onSelect={vi.fn()} offShift={new Set()} />)
    expect(screen.queryAllByRole('button')).toHaveLength(0)
    expect(container.querySelectorAll('[tabindex]')).toHaveLength(0)
    expect(screen.getByRole('img', { name: /^Fab floor plan.*thumbnail/ })).toBeInTheDocument()
  })
})

describe('live region', () => {
  it('is one polite status for toasts; the dispatch log is not live', async () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const api = mockApi({ ...workspaceRoutes(), ...liveRoutes() })
    localStorage.setItem('fab-dispatch-demo-token', 'demo-dispatcher')
    history.replaceState(null, '', `/?shift=${fixtures.shift.state.id}`)
    render(<AuthProvider><Wrapped /></AuthProvider>)
    const log = await screen.findByRole('region', { name: 'Dispatch log' })
    expect(log).not.toHaveAttribute('aria-live')
    const live = document.querySelectorAll('[aria-live]')
    expect([...live].map((el) => `${el.className}:${el.getAttribute('aria-live')}:${el.getAttribute('role')}`)).toEqual(['toasts:polite:status'])
    expect(within(live[0]).queryAllByRole('status')).toHaveLength(0)
    expect(api.find('GET', `/shifts/${fixtures.shift.state.id}`).length).toBeGreaterThan(0)
  })
})

function Wrapped() {
  // The live view needs a signed-in user; AuthProvider resolves the demo token above.
  const auth = useAuth()
  if (auth.status !== 'signedIn') return null
  return <LiveShift scenario={scenario} preset="normal" weights={fixtures.meta.default_weights} areas={areas} profile={fab1} canDispatch onError={() => {}} />
}
