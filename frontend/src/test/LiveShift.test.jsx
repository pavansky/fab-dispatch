// Live dispatch through the whole app: start, drive the clock, stream events, roles.
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clock } from '../lib/format.js'
import { setTokenProvider } from '../api.js'
import { RECONNECT_MS } from '../lib/stream.js'
import { errorBody, fixtures, json, liveRoutes, mockApi, workspaceRoutes } from './api.js'
import { FakeEventSource, renderApp, signInAs } from './app.jsx'

const { shift, shiftAdvanced, shiftEvents, shifts } = fixtures
const id = shift.state.id
const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
  RECONNECT_MS.first = 20 // reconnect fast in tests; the doubling and cap are tested on the values
})
afterEach(() => { RECONNECT_MS.first = 1000 })

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

  it('subscribes to the shift stream with a short-lived ticket and shows each event in the log', async () => {
    const ctx = await openLive()
    await startShift(ctx)
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const es = FakeEventSource.latest()
    expect(ctx.api.find('POST', `/shifts/${id}/stream-ticket`)).toHaveLength(1)
    expect(es.url).toBe(`/api/shifts/${id}/stream?ticket=ticket-1`)
    expect(es.url).not.toContain('access_token') // the long-lived token stays out of URLs and logs
    await waitFor(() => expect(screen.getByText('live')).toBeInTheDocument())
    const event = shiftEvents.find((e) => e.kind === 'replanned')
    es.emit(event)
    expect(await within(screen.getByRole('region', { name: 'Dispatch log' })).findByText(new RegExp(`^${escape(event.message)}`))).toBeInTheDocument()
    await waitFor(() => expect(ctx.api.find('GET', `/shifts/${id}`).length).toBeGreaterThan(1)) // refetch on event
  })

  it('reopens a dropped stream with a new ticket, resuming after the last event, and backs off', async () => {
    const live = liveRoutes()
    const stamps = []
    let failTickets = 0
    const ctx = await openLive('dispatcher', {
      [`POST /shifts/${id}/stream-ticket`]: (req) => {
        stamps.push(Date.now())
        return failTickets-- > 0 ? json(503, errorBody('unavailable', 'down')) : live[`POST /shifts/${id}/stream-ticket`](req)
      },
    })
    await startShift(ctx)
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const first = FakeEventSource.latest()
    await waitFor(() => expect(screen.getByText('live')).toBeInTheDocument())
    first.emit({ ...shiftEvents[0], id: 7 })
    first.onerror()
    expect(first.closed).toBe(true) // EventSource's own retry would reuse the expired ticket
    await waitFor(() => expect(screen.getByText('reconnecting')).toBeInTheDocument())
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2))
    const second = FakeEventSource.latest()
    expect(second.url).toBe(`/api/shifts/${id}/stream?ticket=ticket-2&after=7`)
    expect(stamps).toHaveLength(2)
    await waitFor(() => expect(screen.getByText('live')).toBeInTheDocument())
    // While no ticket can be had, the waits double: 20, 40, 80 ms here (1, 2, 4 s in the app).
    failTickets = 2
    second.onerror()
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(3), { timeout: 2000 })
    expect(stamps).toHaveLength(5)
    expect(stamps[3] - stamps[2]).toBeGreaterThanOrEqual(35)
    expect(stamps[4] - stamps[3]).toBeGreaterThanOrEqual(70)
    expect(FakeEventSource.latest().url).toBe(`/api/shifts/${id}/stream?ticket=ticket-3&after=7`)
  })

  it('falls back to the token in the query where the API has no tickets, read fresh at each connect', async () => {
    const ctx = await openLive('dispatcher', { [`POST /shifts/${id}/stream-ticket`]: json(404, errorBody('not_found', 'no such route')) })
    await startShift(ctx)
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    expect(FakeEventSource.latest().url).toBe(`/api/shifts/${id}/stream?access_token=demo-dispatcher`)
    setTokenProvider(() => 'rotated-token') // Supabase rotated the token while the stream was up
    FakeEventSource.latest().onerror()
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2))
    expect(FakeEventSource.latest().url).toBe(`/api/shifts/${id}/stream?access_token=rotated-token`)
  })

  it('keeps trying when no ticket can be had, instead of dying', async () => {
    let fail = true
    const ctx = await openLive('dispatcher', {
      [`POST /shifts/${id}/stream-ticket`]: () => (fail ? json(503, errorBody('unavailable', 'down')) : { ticket: 'late', expires_in: 90 }),
    })
    await startShift(ctx)
    await waitFor(() => expect(ctx.api.find('POST', `/shifts/${id}/stream-ticket`).length).toBeGreaterThan(1))
    expect(FakeEventSource.instances).toHaveLength(0)
    fail = false
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1), { timeout: 2000 })
    expect(FakeEventSource.latest().url).toContain('ticket=late')
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
    expect(call.headers['If-Match']).toBe(`"${shift.version}"`) // the version this view had seen
    expect(screen.getByText(/Clock driven by/)).toHaveTextContent('Clock driven by you')
  })

  it("refuses to write over someone else's change: shows the latest shift, says so, never retries", async () => {
    const { events: _e, ...advanced } = shiftAdvanced
    const { events: _c, ...base } = shift
    let current = base // version 1 until someone else advances the clock behind this view's back
    const ctx = await openLive('dispatcher', {
      [`GET /shifts/${id}`]: () => json(200, current, { etag: `"${current.version}"` }),
      [`POST /shifts/${id}/advance`]: ({ headers }) => {
        if (headers['If-Match'] === `"${current.version}"` && current === advanced) return shiftAdvanced
        current = advanced // another dispatcher's write won the race
        return json(409, errorBody('conflict', `shift changed (now version ${advanced.version}); reload and retry`))
      },
    })
    await startShift(ctx)
    expect(screen.getByText('Shift clock').nextSibling).toHaveTextContent(clock(shift.state.clock))
    const reads = ctx.api.find('GET', `/shifts/${id}`).length
    await ctx.user.click(screen.getByRole('button', { name: '+1 h' }))
    expect(await screen.findByText('Someone else changed this shift; showing the latest')).toBeInTheDocument()
    await waitFor(() => expect(ctx.api.find('GET', `/shifts/${id}`).length).toBeGreaterThan(reads))
    await waitFor(() => expect(screen.getByText('Shift clock').nextSibling).toHaveTextContent(clock(advanced.state.clock)))
    expect(ctx.api.find('POST', `/shifts/${id}/advance`)).toHaveLength(1) // no blind retry
    // The next write pins the version just shown.
    await ctx.user.click(screen.getByRole('button', { name: '+1 h' }))
    await waitFor(() => expect(ctx.api.find('POST', `/shifts/${id}/advance`)).toHaveLength(2))
    expect(ctx.api.find('POST', `/shifts/${id}/advance`)[1].headers['If-Match']).toBe(`"${advanced.version}"`)
  })

  it('pins the version on reported jobs and releases too', async () => {
    const ctx = await openLive()
    await startShift(ctx)
    await ctx.user.click(screen.getByRole('button', { name: 'Play' }))
    await waitFor(() => expect(ctx.api.find('POST', `/shifts/${id}/advance`).length).toBeGreaterThan(0), { timeout: 2500 })
    await waitFor(() => expect(screen.getByText(/Clock driven by/)).toHaveTextContent('you'))
    await ctx.user.click(screen.getByRole('button', { name: 'Pause' }))
    await waitFor(() => expect(ctx.api.find('POST', `/shifts/${id}/release`)).toHaveLength(1))
    expect(ctx.api.find('POST', `/shifts/${id}/release`)[0].headers['If-Match']).toBe(`"${shiftAdvanced.version}"`)
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
      expect(ctx.api.find('POST', `/shifts/${id}/jobs`)[0].headers['If-Match']).toBe(`"${shift.version}"`)
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
