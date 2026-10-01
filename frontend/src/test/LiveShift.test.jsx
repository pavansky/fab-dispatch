// Live dispatch through the whole app: start, drive the clock, stream events, roles.
import { screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clock } from '../lib/format.js'
import { errorBody, fixtures, json, liveRoutes, workspaceRoutes } from './api.js'
import { FakeEventSource, signInAs } from './app.jsx'

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
