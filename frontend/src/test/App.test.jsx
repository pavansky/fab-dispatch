// The whole app against a fake backend that serves real API fixtures: sign-in, roles,
// the planning workspace, navigation, theme and fab switching.
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { recommend } from '../lib/analysis.js'
import { ALGO_ORDER, ALGO_SHORT } from '../lib/metrics.js'
import { errorBody, fixtures, json, mockApi, workspaceRoutes } from './api.js'
import { renderApp, signInAs } from './app.jsx'

const results = ALGO_ORDER.map((a) => fixtures.plans[a])

describe('sign-in', () => {
  it('offers one-click demo roles in local mode', async () => {
    mockApi(workspaceRoutes())
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Continue as Dispatcher' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Continue as Viewer' })).toBeEnabled()
  })

  it('asks only for an email when Supabase Auth is on: no password to have forgotten', async () => {
    mockApi({ ...workspaceRoutes(), 'GET /auth/config': { mode: 'supabase', supabase_url: 'https://example.supabase.co', supabase_publishable_key: 'sb_publishable_test' } })
    const user = renderApp()
    expect(await screen.findByLabelText('Email')).toBeRequired()
    expect(screen.queryByRole('button', { name: /Continue as/ })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /password/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Email me a sign-in code' })).toHaveAccessibleDescription(/No password and no sign-up/)
    expect(user).toBeTruthy()
  })

  it('signs in as a dispatcher, remembers the session and lands on the workspace', async () => {
    const { api } = await signInAs('dispatcher')
    expect(api.find('POST', '/auth/demo')[0].body).toEqual({ role: 'dispatcher' })
    expect(localStorage.getItem('fab-dispatch-demo-token')).toBe('demo-dispatcher')
    expect(api.find('GET', '/auth/me')[0].headers.Authorization).toBe('Bearer demo-dispatcher')
  })

  it('drops a stored session the server rejects and shows sign-in again', async () => {
    localStorage.setItem('fab-dispatch-demo-token', 'revoked')
    mockApi({ ...workspaceRoutes(), 'GET /auth/me': json(401, errorBody('unauthorized', 'Invalid token')) })
    renderApp()
    expect(await screen.findByRole('button', { name: 'Continue as Dispatcher' })).toBeInTheDocument()
    expect(localStorage.getItem('fab-dispatch-demo-token')).toBeNull()
  })

  it('tells the user when the API is unreachable', async () => {
    mockApi({ 'GET /auth/config': () => { throw new TypeError('Failed to fetch') } })
    renderApp()
    expect(await screen.findByText(/Can't reach the API/)).toBeInTheDocument()
  })

  it('signs out from the user menu', async () => {
    const { user } = await signInAs('dispatcher')
    await user.click(screen.getByRole('button', { name: 'D' }))
    expect(screen.getByRole('menu')).toHaveTextContent('dispatcher@demo.local')
    await user.click(screen.getByRole('menuitem', { name: 'Sign out' }))
    expect(await screen.findByRole('button', { name: 'Continue as Dispatcher' })).toBeInTheDocument()
    expect(localStorage.getItem('fab-dispatch-demo-token')).toBeNull()
  })
})

describe('planning workspace', () => {
  it('solves the shift with all five strategies and recommends one', async () => {
    const { api } = await signInAs('dispatcher')
    await waitFor(() => expect(api.find('POST', '/plan')).toHaveLength(5))
    expect(new Set(api.find('POST', '/plan').map((c) => c.body.algorithm))).toEqual(new Set(ALGO_ORDER))
    const winner = recommend(results, 'value').winner
    const card = await screen.findByRole('region', { name: 'Recommendation' })
    await waitFor(() => expect(within(card).getByRole('heading', { level: 2 })).toHaveTextContent(winner.label))
    for (const a of ALGO_ORDER) expect(screen.getAllByText(ALGO_SHORT[a]).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Recommended').length).toBeGreaterThan(0)
  })

  it('re-plans every strategy when a cost weight changes', async () => {
    const { api } = await signInAs('dispatcher')
    await waitFor(() => expect(api.find('POST', '/plan')).toHaveLength(5))
    const walking = screen.getByRole('slider', { name: 'Walking' })
    const next = fixtures.meta.default_weights.travel_100m + 0.5
    fireEvent.change(walking, { target: { value: String(next) } }) // what a drag does
    await waitFor(() => expect(api.find('POST', '/plan')).toHaveLength(10), { timeout: 2000 })
    expect(api.find('POST', '/plan').slice(5).every((c) => c.body.weights.travel_100m === next)).toBe(true)
    expect(screen.getByText(String(next))).toBeInTheDocument()
  })

  it('opens a view from the tabs and keeps it in the URL', async () => {
    const { user } = await signInAs('dispatcher')
    await user.click(screen.getByRole('tab', { name: /Floor plan/ }))
    expect(screen.getByRole('tab', { name: /Floor plan/ })).toHaveAttribute('aria-selected', 'true')
    expect(new URL(location.href).searchParams.get('tab')).toBe('floor')
    expect(await screen.findByRole('group', { name: /Fab floor plan/ })).toBeInTheDocument()
  })

  it('explains a job picked on the floor plan, per strategy', async () => {
    const { user } = await signInAs('dispatcher')
    await user.click(screen.getByRole('tab', { name: /Floor plan/ }))
    await user.click(await screen.findByRole('button', { name: /^J006,/ }))
    const inspector = screen.getByRole('complementary', { name: 'Inspector' })
    expect(within(inspector).getByRole('heading', { level: 3 })).toHaveTextContent('J006')
    expect(within(inspector).getByText('Unassigned')).toBeInTheDocument() // Greedy leaves it
    expect(new URL(location.href).searchParams.get('job')).toBe('J006')
  })

  it('starts in the light theme and remembers a change', async () => {
    const { user } = await signInAs('dispatcher')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(screen.getByRole('button', { name: 'Light' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(screen.getByRole('button', { name: 'Dark' }))
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('fab-dispatch-theme')).toBe('dark')
    await user.click(screen.getByRole('button', { name: 'Auto' }))
    expect(document.documentElement).not.toHaveAttribute('data-theme')
  })

  it('switches fab: new profile, new scenario, that fab’s presets', async () => {
    const { api, user } = await signInAs('dispatcher')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Fab' }), fixtures.fab2.id)
    await waitFor(() => expect(api.find('GET', `/fabs/${fixtures.fab2.id}`)).toHaveLength(1))
    await waitFor(() => expect(api.find('POST', '/scenario').at(-1).body.fab_id).toBe(fixtures.fab2.id))
    const preset = await screen.findByRole('combobox', { name: 'Preset' })
    await waitFor(() => expect(within(preset).getByRole('option', { name: 'Photo crunch' })).toBeInTheDocument())
    expect(new URL(location.href).searchParams.get('fab')).toBe(fixtures.fab2.id)
  })
})

describe('roles', () => {
  it('lets a viewer explore but not run benchmarks', async () => {
    const { user } = await signInAs('viewer')
    await user.click(screen.getByRole('tab', { name: /Benchmark/ }))
    expect(screen.getByRole('button', { name: 'Run benchmark' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Measure gaps' })).toBeDisabled()
    expect(screen.getByText(/need the dispatcher role/)).toBeInTheDocument()
  })

  it('lets a dispatcher run the benchmark for every preset of the fab', async () => {
    const { api, user } = await signInAs('dispatcher')
    await user.click(screen.getByRole('tab', { name: /Benchmark/ }))
    await user.click(screen.getByRole('button', { name: 'Run benchmark' }))
    await screen.findByRole('button', { name: 'Re-run benchmark' }, { timeout: 4000 })
    const presets = Object.keys(fixtures.fab1.presets)
    expect(api.find('POST', '/benchmark').map((c) => c.body.preset)).toEqual(presets)
    expect(api.find('POST', '/benchmark').every((c) => c.body.fab_id === fixtures.fab1.id)).toBe(true)
    for (const p of presets) expect(screen.getByRole('heading', { name: new RegExp(fixtures.fab1.presets[p].label) })).toBeInTheDocument()
    expect(screen.getAllByText(/Best value:/)).toHaveLength(presets.length)
  })
})

describe('views', () => {
  it('re-ranks the strategies when the planning goal changes', async () => {
    const { user } = await signInAs('dispatcher')
    const card = screen.getByRole('region', { name: 'Recommendation' })
    await waitFor(() => expect(within(card).getByRole('heading', { level: 2 })).toHaveTextContent(recommend(results, 'value').winner.label))
    await user.selectOptions(within(card).getByRole('combobox', { name: 'Planning goal' }), 'cost')
    expect(within(card).getByRole('heading', { level: 2 })).toHaveTextContent(recommend(results, 'cost').winner.label)
  })

  it('opens a job the strategies disagree on in the floor plan', async () => {
    const { user } = await signInAs('dispatcher')
    await waitFor(() => expect(screen.getByRole('heading', { name: /Where the strategies disagree/ })).toBeInTheDocument())
    const row = (await screen.findAllByText('J006')).map((el) => el.closest('tr')).find(Boolean)
    await user.click(row)
    expect(screen.getByRole('tab', { name: /Floor plan/ })).toHaveAttribute('aria-selected', 'true')
    expect(within(screen.getByRole('complementary', { name: 'Inspector' })).getByRole('heading', { level: 3 })).toHaveTextContent('J006')
  })

  it("jumps from a strategy's scorecard to its floor plan", async () => {
    const { user } = await signInAs('dispatcher')
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'View on floor plan' })).toHaveLength(5))
    await user.click(screen.getAllByRole('button', { name: 'View on floor plan' })[1]) // Hungarian
    expect(screen.getByRole('group', { name: `Fab floor plan, ${fixtures.plans.hungarian.label}` })).toBeInTheDocument()
    expect(within(screen.getByRole('group', { name: 'Strategy' })).getByRole('button', { name: /Hungarian/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('shows every engineer on the schedule with their jobs in time order', async () => {
    const { user } = await signInAs('dispatcher')
    await user.click(screen.getByRole('tab', { name: /Schedule/ }))
    const table = screen.getByRole('table', { name: `Shift schedule, ${fixtures.plans.pyvrp.label}` })
    expect(within(table).getAllByRole('row')).toHaveLength(fixtures.scenario.engineers.length + 1)
    const route = fixtures.plans.pyvrp.routes.find((r) => r.stops.length)
    for (const s of route.stops) expect(within(table).getByLabelText(new RegExp(`^${s.job_id} `))).toBeInTheDocument()
  })

  it('explains unserved work as a staffing question on the workforce view', async () => {
    const { user } = await signInAs('dispatcher')
    await user.click(screen.getByRole('tab', { name: /Workforce/ }))
    expect(screen.getByRole('heading', { name: 'Demand vs certified supply' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Certification matrix' })).toBeInTheDocument()
    const unserved = screen.getByRole('heading', { name: `Unserved work · ${fixtures.plans.pyvrp.label}` }).closest('section')
    const rows = within(unserved).getAllByRole('row').slice(1)
    expect(rows.map((r) => r.cells[0].querySelector('b').textContent)).toEqual(fixtures.plans.pyvrp.unassigned.map((u) => u.job_id))
    rows.forEach((r, i) => expect(r).toHaveTextContent(fixtures.plans.pyvrp.unassigned[i].reason))
  })

  it('takes an engineer off shift and re-plans without them', async () => {
    const { api, user } = await signInAs('dispatcher')
    await waitFor(() => expect(api.find('POST', '/plan')).toHaveLength(5))
    await user.click(screen.getByRole('tab', { name: /Floor plan/ }))
    await user.click(screen.getByRole('button', { name: /^Engineer E01,/ }))
    await user.click(screen.getByRole('button', { name: 'Take off shift (what-if)' }))
    await waitFor(() => expect(api.find('POST', '/plan')).toHaveLength(10), { timeout: 2000 })
    const replanned = api.find('POST', '/plan').at(-1).body.scenario.engineers.map((e) => e.id)
    expect(replanned).not.toContain('E01')
    expect(replanned).toHaveLength(fixtures.scenario.engineers.length - 1)
    expect(screen.getByRole('button', { name: 'Restore all 1 engineers' })).toBeInTheDocument()
  })
})

describe('guest access', () => {
  const supabaseConfig = (guest_role) => ({ mode: 'supabase', supabase_url: 'https://example.supabase.co', supabase_publishable_key: 'sb_publishable_test', guest_role })

  it('offers a one-click guest sign-in when guests are welcome', async () => {
    mockApi({ ...workspaceRoutes(), 'GET /auth/config': supabaseConfig('dispatcher') })
    renderApp()
    expect(await screen.findByRole('button', { name: 'Try it as a guest' })).toBeEnabled()
    expect(screen.getByText(/Guests get full dispatcher access/)).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toBeInTheDocument() // email still available
  })

  it('hides it when guest access is off', async () => {
    mockApi({ ...workspaceRoutes(), 'GET /auth/config': supabaseConfig(null) })
    renderApp()
    expect(await screen.findByLabelText('Email')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Try it as a guest' })).not.toBeInTheDocument()
  })
})
