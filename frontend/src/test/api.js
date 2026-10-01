// A fake backend for component tests. Responses come from fixtures captured from the real
// API (backend/scripts/export_ui_fixtures.py), so the UI is tested against real shapes.
import { vi } from 'vitest'
import authConfig from './fixtures/auth_config.json'
import me from './fixtures/me.json'
import meta from './fixtures/meta.json'
import fabs from './fixtures/fabs.json'
import fab1 from './fixtures/fab1.json'
import fab2 from './fixtures/fab2.json'
import scenario from './fixtures/scenario.json'
import scenarioFab2 from './fixtures/scenario_fab2.json'
import plans from './fixtures/plans.json'
import benchmark from './fixtures/benchmark.json'
import shift from './fixtures/shift.json'
import shiftAdvanced from './fixtures/shift_advanced.json'
import shiftEvents from './fixtures/shift_events.json'
import shifts from './fixtures/shifts.json'
import helpIndex from './fixtures/help_index.json'
import helpArticles from './fixtures/help_articles.json'
import helpSearch from './fixtures/help_search.json'
import helpAnchors from './fixtures/help_anchors.json'
import askJob from './fixtures/ask_job.json'
import askDocs from './fixtures/ask_docs.json'
import askUnknown from './fixtures/ask_unknown.json'

export const fixtures = {
  authConfig, me, meta, fabs, fab1, fab2, scenario, scenarioFab2, plans, benchmark, shift, shiftAdvanced, shiftEvents, shifts,
  helpIndex, helpArticles, helpSearch, helpAnchors, askJob, askDocs, askUnknown,
}

export const json = (status, body, headers = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...headers } })

export const errorBody = (code, message) => ({ error: { code, message, request_id: 'req-test' } })

const never = () => new Promise(() => {})

/** Everything a signed-in workspace needs, keyed "METHOD /path". Override per test. */
export function workspaceRoutes({ role = 'dispatcher' } = {}) {
  return {
    'GET /auth/config': authConfig,
    'POST /auth/demo': ({ body }) => ({ access_token: `demo-${body.role}`, token_type: 'bearer' }),
    'GET /auth/me': ({ headers }) => {
      const auth = headers?.Authorization ?? ''
      if (!auth) return json(401, errorBody('unauthorized', 'Sign in required'))
      const r = auth.endsWith('viewer') ? 'viewer' : role
      return { ...me, id: `demo-${r}`, email: `${r}@demo.local`, role: r }
    },
    'GET /meta': meta,
    'GET /fabs': fabs,
    'GET /fabs/fab1-300mm-logic': fab1,
    'GET /fabs/fab2-200mm-analog': fab2,
    'POST /scenario': ({ body }) => (body.fab_id === fab2.id ? scenarioFab2 : scenario),
    // Fab 2 plans aren't in the fixtures; they stay "solving", which the fab-switch test doesn't need.
    'POST /plan': ({ body }) => (body.scenario.fab_id === fab1.id ? plans[body.algorithm] : never()),
    'POST /benchmark': ({ body }) => ({ ...benchmark, preset: body.preset, runs: benchmark.runs.map((r) => ({ ...r, preset: body.preset })) }),
    'GET /shifts': [],
    'GET /help': helpIndex,
    'GET /help/search': ({ url }) => ({ ...helpSearch, query: new URL(url, 'http://x').searchParams.get('q') }),
    ...Object.fromEntries(Object.entries(helpArticles).map(([slug, a]) => [`GET /help/${slug}`, a])),
    // The assistant's real answers for three kinds of question.
    'POST /assistant/ask': ({ body }) => (/J006/.test(body.question) ? askJob : /joke/i.test(body.question) ? askUnknown : askDocs),
  }
}

/** A live shift on the server: created, viewable, advanceable. */
export function liveRoutes() {
  const id = shift.state.id
  const { events: _created, ...view } = shift
  let current = view
  return {
    'GET /shifts': shifts,
    'POST /shifts': shift,
    // Conditional GET like the real API: an unchanged shift answers 304 to its ETag.
    [`GET /shifts/${id}`]: ({ headers }) => {
      const tag = `"${current.version}"`
      return headers['If-None-Match'] === tag ? new Response(null, { status: 304, headers: { etag: tag } }) : json(200, current, { etag: tag })
    },
    [`POST /shifts/${id}/advance`]: () => { const { events: _e, ...v } = shiftAdvanced; current = v; return shiftAdvanced },
    [`POST /shifts/${id}/release`]: () => current,
    [`GET /shifts/${id}/events`]: shiftEvents,
  }
}

/**
 * Replace fetch with a router over `routes`. Each handler gets { body, url, headers } and
 * returns a JSON-able value, a Response, or a promise of either. Unknown routes are 404s,
 * so a test fails loudly when the UI calls something unexpected.
 */
export function mockApi(routes) {
  const calls = []
  const fetchMock = vi.fn(async (url, init = {}) => {
    const method = init.method ?? 'GET'
    const [path] = String(url).replace(/^\/api/, '').split('?')
    const body = init.body ? JSON.parse(init.body) : undefined
    const headers = init.headers ?? {}
    calls.push({ method, path, url: String(url), body, headers })
    const handler = routes[`${method} ${path}`]
    if (handler === undefined) return json(404, errorBody('not_found', `no mock for ${method} ${path}`))
    const out = typeof handler === 'function' ? await handler({ body, url: String(url), headers }) : handler
    return out instanceof Response ? out : json(200, out)
  })
  vi.stubGlobal('fetch', fetchMock)
  const find = (method, path) => calls.filter((c) => c.method === method && c.path === path)
  return { calls, fetchMock, find }
}
