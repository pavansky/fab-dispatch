// The planning workspace's requests and what-ifs: request sequencing, applied vs typed
// sizes, history durations, hand-reported jobs, and the strategy being viewed.
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { fixtures, workspaceRoutes } from './api.js'
import { signInAs } from './app.jsx'

const { scenario, fab1, fab2, plans } = fixtures
const never = () => new Promise(() => {})
const later = (ms, value) => new Promise((r) => setTimeout(() => r(value), ms))
const lastPlan = (api) => api.find('POST', '/plan').at(-1).body.scenario

// jsdom has no SVG geometry: map client coordinates straight to floor metres (y measured up).
const svgProto = window.SVGSVGElement?.prototype ?? window.SVGElement.prototype
beforeEach(() => {
  svgProto.createSVGPoint = () => ({ x: 0, y: 0, matrixTransform() { return { x: this.x, y: this.y } } })
  svgProto.getScreenCTM = () => ({ inverse: () => ({}) })
})
afterEach(() => {
  delete svgProto.createSVGPoint
  delete svgProto.getScreenCTM
})

/** Report a job by tapping the middle of a tool family's area on the floor plan. */
async function reportJobAt(user, family) {
  const toggle = screen.getByRole('checkbox', { name: 'Report a job by tapping the floor' })
  if (!toggle.checked) await user.click(toggle)
  const [x0, y0, x1, y1] = fab1.families.find((f) => f.id === family).area
  const floor = await screen.findByRole('group', { name: /^Fab floor plan/ })
  fireEvent.click(floor, { clientX: (x0 + x1) / 2, clientY: scenario.settings.floor_height - (y0 + y1) / 2 })
}

describe('requests', () => {
  it('lets only the latest shift request land (a late answer never strands the fab on "Loading shift…")', async () => {
    const routes = workspaceRoutes()
    const base = routes['POST /scenario']
    // Fab 1's excursion shift answers late: after the switch to fab 2 has been answered.
    routes['POST /scenario'] = (req) => (req.body.preset === 'excursion' && req.body.fab_id === fab1.id ? later(80, scenario) : base(req))
    const { api, user } = await signInAs('dispatcher', routes)
    await user.selectOptions(screen.getByRole('combobox', { name: 'Preset' }), 'excursion')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Fab' }), fab2.id)
    await waitFor(() => expect(api.find('POST', '/scenario').at(-1).body.fab_id).toBe(fab2.id))
    await later(150)
    expect(screen.queryByText(/Loading shift/)).not.toBeInTheDocument()
    expect(within(screen.getByRole('combobox', { name: 'Preset' })).getByRole('option', { name: 'Photo crunch' })).toBeInTheDocument()
    expect(new URL(location.href).searchParams.get('fab')).toBe(fab2.id)
  })

  it('a preset change keeps the applied sizes when the typed ones are invalid', async () => {
    const { api, user } = await signInAs('dispatcher')
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Engineers' }), { target: { value: '' } })
    await user.selectOptions(screen.getByRole('combobox', { name: 'Preset' }), 'excursion')
    await waitFor(() => expect(api.find('POST', '/scenario').at(-1).body.preset).toBe('excursion'))
    expect(api.find('POST', '/scenario').at(-1).body).toMatchObject({ seed: 7, n_engineers: 14, n_jobs: 45 })
  })

  it('benchmarks the sizes on screen, not unapplied typed ones', async () => {
    const { api, user } = await signInAs('dispatcher')
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Engineers' }), { target: { value: '30' } })
    await user.click(screen.getByRole('tab', { name: /Benchmark/ }))
    expect(await screen.findByText(/\(14 engineers, 45 jobs, current weights\)/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Run benchmark' }))
    await waitFor(() => expect(api.find('POST', '/benchmark').length).toBeGreaterThan(0))
    expect(api.find('POST', '/benchmark')[0].body.n_engineers).toBe(14)
  })
})

describe('the strategy being viewed', () => {
  it("shows a solving state for the pressed strategy instead of drawing another's plan", async () => {
    const routes = workspaceRoutes()
    routes['POST /plan'] = ({ body }) => (body.algorithm === 'pyvrp' ? never() : plans[body.algorithm])
    const { user } = await signInAs('dispatcher', routes)
    await user.click(screen.getByRole('tab', { name: /Floor plan/ }))
    expect(await within(screen.getByRole('main')).findByText('Solving PyVRP…')).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: /^Fab floor plan/ })).not.toBeInTheDocument()
    expect(within(screen.getByRole('group', { name: 'Strategy' })).getByRole('button', { name: /PyVRP/ })).toHaveAttribute('aria-pressed', 'true')
  })
})

describe('what-ifs', () => {
  const predictRoute = ({ body }) => ({
    scenario: { ...body, jobs: body.jobs.map((j) => (j.kind === 'down' ? { ...j, duration: j.duration + 30 } : j)) },
    changes: body.jobs.filter((j) => j.kind === 'down').map((j) => ({ job_id: j.id, standard: j.duration, predicted: j.duration + 30 })),
  })

  it('turning history durations off restores durations only, keeping jobs reported meanwhile', async () => {
    const { api, user } = await signInAs('dispatcher', { ...workspaceRoutes(), 'POST /repairs/predict-durations': predictRoute })
    const durations = Object.fromEntries(scenario.jobs.map((j) => [j.id, j.duration]))
    const firstDown = scenario.jobs.find((j) => j.kind === 'down')
    await user.click(screen.getByRole('checkbox', { name: 'Plan with history-predicted durations' }))
    await waitFor(() => expect(lastPlan(api).jobs.find((j) => j.id === firstDown.id).duration).toBe(firstDown.duration + 30), { timeout: 2000 })

    await reportJobAt(user, 'etch')
    await waitFor(() => expect(lastPlan(api).jobs).toHaveLength(scenario.jobs.length + 1), { timeout: 2000 })
    const added = lastPlan(api).jobs.at(-1)

    await user.click(screen.getByRole('checkbox', { name: 'Plan with history-predicted durations' }))
    await waitFor(() => expect(lastPlan(api).jobs.find((j) => j.id === firstDown.id).duration).toBe(firstDown.duration), { timeout: 2000 })
    const after = lastPlan(api).jobs
    expect(after).toHaveLength(scenario.jobs.length + 1)
    expect(after.at(-1)).toEqual(added)
    expect(after.slice(0, -1).every((j) => j.duration === durations[j.id])).toBe(true)
  })

  it("gives a hand-reported job the response target of the shift's fab and preset", async () => {
    const { api, user } = await signInAs('dispatcher')
    await reportJobAt(user, 'deposition')
    await waitFor(() => expect(lastPlan(api).jobs).toHaveLength(scenario.jobs.length + 1), { timeout: 2000 })
    const job = lastPlan(api).jobs.at(-1)
    expect(job).toMatchObject({ skill: 'deposition', priority: 3, earliest: 120 })
    // The fixture shift's bottleneck downs all have a 45-minute window.
    expect(job.latest - job.earliest).toBe(45)
  })

  it('takes the response target from the profile when the API includes it', async () => {
    const routes = workspaceRoutes()
    routes[`GET /fabs/${fab1.id}`] = { ...fab1, presets: { ...fab1.presets, normal: { ...fab1.presets.normal, sla_critical: 30, sla_down: 90 } } }
    const { api, user } = await signInAs('dispatcher', routes)
    await reportJobAt(user, 'deposition')
    await waitFor(() => expect(lastPlan(api).jobs).toHaveLength(scenario.jobs.length + 1), { timeout: 2000 })
    const job = lastPlan(api).jobs.at(-1)
    expect(job.latest - job.earliest).toBe(30)
  })
})
