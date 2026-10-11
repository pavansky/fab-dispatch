// Live dispatch through the whole app: start, drive the clock, stream events, roles.
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clock } from '../lib/format.js'
import { errorBody, fixtures, json, liveRoutes, mockApi, workspaceRoutes } from './api.js'
import { FakeEventSource, renderApp, signInAs } from './app.jsx'

const { shift, shiftAdvanced, shiftEvents, shifts } = fixtures
const id = shift.state.id
const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
})

async function openLive(role = 'dispatcher', extra = {}) {
  const ctx = await signInAs(role, { ...workspaceRoutes(), ...liveRoutes(), ...extra })
  await ctx.user.click(screen.getByRole('tab', { name: /Live dispatch/ }))
  return ctx
}

async function startShift(ctx) {
  await ctx.user.click(await screen.findByRole('button', { name: 'Start live shift' }))
  await screen.findByRole('region', { name: 'Dispatch log' })
}

describe('live dispatch', () => {
  it('lists recent shifts for the fab so anyone can rejoin', async () => {
    await openLive()
    const row = (await screen.findByText(shifts[0].id)).closest('tr')
    expect(within(row).getByText(shifts[0].created_by)).toBeInTheDocument()
    expect(within(row).getByText('Running')).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'Join' })).toBeInTheDocument()
  })

  it('starts a shift on the server with the chosen strategy and opens it', async () => {
    const ctx = await openLive()
    await ctx.user.selectOptions(screen.getByRole('combobox', { name: 'Re-dispatch strategy' }), 'pyvrp')
    await startShift(ctx)
    const created = ctx.api.find('POST', '/shifts')[0].body
    expect(created.algorithm).toBe('pyvrp')
    expect(created.scenario.jobs).toHaveLength(fixtures.scenario.jobs.length)
    expect(new URL(location.href).searchParams.get('shift')).toBe(id)
    expect(screen.getByText('Shift clock').nextSibling).toHaveTextContent(clock(shift.state.clock))
    expect(screen.getByRole('button', { name: 'Play' })).toBeEnabled()
  })

  it('subscribes to the shift stream and shows each event in the log', async () => {
    const ctx = await openLive()
    await startShift(ctx)
    const es = FakeEventSource.latest()
    expect(es.url).toBe(`/api/shifts/${id}/stream?access_token=demo-dispatcher`)
    await waitFor(() => expect(screen.getByText('live')).toBeInTheDocument())
    const event = shiftEvents.find((e) => e.kind === 'replanned')
    es.emit(event)
    expect(await within(screen.getByRole('region', { name: 'Dispatch log' })).findByText(new RegExp(`^${escape(event.message)}`))).toBeInTheDocument()
    await waitFor(() => expect(ctx.api.find('GET', `/shifts/${id}`).length).toBeGreaterThan(1)) // refetch on event
  })

  it('raises an alert when a bottleneck tool goes down', async () => {
    const ctx = await openLive()
    await startShift(ctx)
    const down = shiftEvents.find((e) => e.kind === 'job_reported')
    FakeEventSource.latest().emit({ ...down, data: { ...down.data, priority: 3 } })
    expect(await screen.findByText(`Bottleneck down: ${down.message}`)).toBeInTheDocument()
  })

  it('advances the clock with a retry-safe request', async () => {
    const ctx = await openLive()
    await startShift(ctx)
    await ctx.user.click(screen.getByRole('button', { name: '+1 h' }))
    await waitFor(() => expect(screen.getByText('Shift clock').nextSibling).toHaveTextContent(clock(shiftAdvanced.state.clock)))
    const call = ctx.api.find('POST', `/shifts/${id}/advance`)[0]
    expect(call.body).toEqual({ minutes: 60 })
    expect(call.headers['Idempotency-Key']).toBeTruthy()
    expect(screen.getByText(/Clock driven by/)).toHaveTextContent('Clock driven by you')
  })

  it('shows a conflict as a notice, not an error page', async () => {
    const ctx = await openLive('dispatcher', {
      [`POST /shifts/${id}/advance`]: json(409, errorBody('conflict', 'ops@fab.example is driving the clock right now')),
    })
    await startShift(ctx)
    await ctx.user.click(screen.getByRole('button', { name: '+1 h' }))
    expect(await screen.findByText('ops@fab.example is driving the clock right now')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Dispatch log' })).toBeInTheDocument()
  })

  it('leaves a shift and returns to the list', async () => {
    const ctx = await openLive()
    await startShift(ctx)
    await ctx.user.click(screen.getByRole('button', { name: 'Leave' }))
    expect(await screen.findByRole('button', { name: 'Start live shift' })).toBeInTheDocument()
    expect(new URL(location.href).searchParams.has('shift')).toBe(false)
    expect(FakeEventSource.latest().closed).toBe(true)
  })

  it('rejoins a shift after leaving it (regression: a cached ETag left the view blank)', async () => {
    const ctx = await openLive()
    await startShift(ctx)
    await ctx.user.click(screen.getByRole('button', { name: 'Leave' }))
    await ctx.user.click((await screen.findAllByRole('button', { name: 'Join' }))[0])
    expect(await screen.findByRole('region', { name: 'Dispatch log' })).toBeInTheDocument()
  })

  it('lets a viewer join and watch, but not drive', async () => {
    const ctx = await openLive('viewer')
    expect(screen.getByRole('button', { name: 'Start live shift' })).toBeDisabled()
    await ctx.user.click(await screen.findByRole('button', { name: 'Join' }))
    expect(await screen.findByText('Viewing only')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Play' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '+1 h' })).not.toBeInTheDocument()
  })
})

describe('live dispatch: leaving and sharing', () => {
  it('takes the shift out of the URL when switching tab, and opens the list on return', async () => {
    const ctx = await openLive()
    await startShift(ctx)
    expect(new URL(location.href).searchParams.get('shift')).toBe(id)
    await ctx.user.click(screen.getByRole('tab', { name: /Overview/ }))
    expect(new URL(location.href).searchParams.has('shift')).toBe(false)
    await ctx.user.click(screen.getByRole('tab', { name: /Live dispatch/ }))
    expect(await screen.findByRole('button', { name: 'Start live shift' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Dispatch log' })).not.toBeInTheDocument()
  })

  it('hands the clock back when the view goes away while playing', async () => {
    const ctx = await openLive()
    await startShift(ctx)
    await ctx.user.click(screen.getByRole('button', { name: 'Play' }))
    await waitFor(() => expect(ctx.api.find('POST', `/shifts/${id}/advance`).length).toBeGreaterThan(0), { timeout: 2500 })
    await waitFor(() => expect(screen.getByText(/Clock driven by/)).toHaveTextContent('you'))
    expect(ctx.api.find('POST', `/shifts/${id}/release`)).toHaveLength(0)
    await ctx.user.click(screen.getByRole('tab', { name: /Overview/ }))
    await waitFor(() => expect(ctx.api.find('POST', `/shifts/${id}/release`)).toHaveLength(1))
  })

  it("doesn't open another fab's shift from a link", async () => {
    history.replaceState(null, '', `/?shift=fab2-200mm-analog.0123456789ab&fab=${fixtures.fab1.id}`)
    const api = mockApi({ ...workspaceRoutes(), ...liveRoutes() })
    const user = renderApp()
    await user.click(await screen.findByRole('button', { name: 'Continue as Dispatcher' }))
    expect(await screen.findByRole('button', { name: 'Start live shift' }, { timeout: 4000 })).toBeInTheDocument()
    expect(api.calls.some((c) => c.path.startsWith('/shifts/fab2'))).toBe(false)
  })

  it('confirms a copied link only when the copy worked', async () => {
    const ctx = await openLive()
    await startShift(ctx)
    // user-event installs a clipboard; make its first write fail, as a denied permission does.
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValueOnce(new Error('denied'))
    await ctx.user.click(screen.getByRole('button', { name: 'Copy link' }))
    expect(await screen.findByText(/Couldn't copy the link/)).toBeInTheDocument()
    expect(screen.queryByText('Share link copied')).not.toBeInTheDocument()
    await ctx.user.click(screen.getByRole('button', { name: 'Copy link' }))
    expect(await screen.findByText('Share link copied')).toBeInTheDocument()
    expect(writeText).toHaveBeenLastCalledWith(location.href)
  })
})

describe('live dispatch: actions', () => {
  it("says why a bottleneck down is unassigned, from the plan's own reason", async () => {
    const down = shift.state.scenario.jobs.find((j) => j.priority === 3)
    const reason = '2 qualified engineer(s), but none can arrive before 07:45.'
    const { events: _e, ...base } = shift
    const view = {
      ...base,
      state: { ...base.state, released: [...base.state.released, down.id], plan: { ...base.state.plan, unassigned: [{ job_id: down.id, reason, rejections: {} }] } },
      status: { ...base.status, [down.id]: 'unassigned' },
    }
    const ctx = await openLive('dispatcher', { 'POST /shifts': view, [`GET /shifts/${id}`]: view })
    await startShift(ctx)
    const alert = (await screen.findAllByRole('alert')).find((a) => /bottleneck tool-down/.test(a.textContent))
    expect(alert).toHaveTextContent(`1 bottleneck tool-down is unassigned. ${down.id}: ${reason}`)
    expect(alert).not.toHaveTextContent(/No qualified engineer can reach/)
  })

  it('reports a tool-down with a unique id and the response target of the fab', async () => {
    const svg = window.SVGSVGElement?.prototype ?? window.SVGElement.prototype
    svg.createSVGPoint = () => ({ x: 0, y: 0, matrixTransform() { return { x: this.x, y: this.y } } })
    svg.getScreenCTM = () => ({ inverse: () => ({}) })
    try {
      const ctx = await openLive('dispatcher', { [`POST /shifts/${id}/jobs`]: shiftAdvanced })
      await startShift(ctx)
      await ctx.user.click(screen.getByRole('checkbox', { name: 'Tap floor to report a bottleneck down' }))
      const [x0, y0, x1, y1] = fixtures.fab1.families.find((f) => f.id === 'etch').area
      fireEvent.click(screen.getByRole('group', { name: /^Fab floor plan/ }), { clientX: (x0 + x1) / 2, clientY: fixtures.scenario.settings.floor_height - (y0 + y1) / 2 })
      await waitFor(() => expect(ctx.api.find('POST', `/shifts/${id}/jobs`)).toHaveLength(1))
      const { job } = ctx.api.find('POST', `/shifts/${id}/jobs`)[0].body
      expect(job.id).toMatch(/^L[0-9A-Z]{9}$/)
      expect(job).toMatchObject({ skill: 'etch', priority: 3, earliest: 0, latest: 45 })
      expect(ctx.api.find('POST', `/shifts/${id}/jobs`)[0].headers['Idempotency-Key']).toBeTruthy()
    } finally {
      delete svg.createSVGPoint
      delete svg.getScreenCTM
    }
  })

  it('sends one action per click, however fast the clicks', async () => {
    const ctx = await openLive('dispatcher', {
      [`POST /shifts/${id}/advance`]: () => new Promise((r) => setTimeout(() => r(shiftAdvanced), 60)),
    })
    await startShift(ctx)
    await ctx.user.dblClick(screen.getByRole('button', { name: '+1 h' }))
    await waitFor(() => expect(screen.getByText('Shift clock').nextSibling).toHaveTextContent(clock(shiftAdvanced.state.clock)))
    expect(ctx.api.find('POST', `/shifts/${id}/advance`)).toHaveLength(1)
  })
})
