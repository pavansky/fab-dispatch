import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { generateScenario, getFab, getMeta, listFabs, predictDurations } from './api.js'
import { SignIn, useAuth } from './auth.jsx'
import { usePlans } from './lib/usePlans.js'
import { applyTheme, loadTheme } from './lib/theme.js'
import { ALGO_ORDER, ALGO_SHORT } from './lib/metrics.js'
import { PRIORITY } from './lib/format.js'
import { areasOf, familyAt, familyLabel, familyPrefix, isConstraint, setActiveFab } from './lib/fab.js'
import { GOALS, recommend } from './lib/analysis.js'
import { HelpContext, TOUR_KEY, parseHelpTarget } from './lib/help.js'
import FloorPlan from './components/FloorPlan.jsx'
import Inspector from './components/Inspector.jsx'
import Overview from './components/Overview.jsx'
import Schedule from './components/Schedule.jsx'
import Workforce from './components/Workforce.jsx'
import Benchmark from './components/Benchmark.jsx'
import LiveShift from './components/LiveShift.jsx'
import TopBar from './components/TopBar.jsx'
import Sidebar from './components/Sidebar.jsx'
import Tour from './components/Tour.jsx'

// Help and the assistant load on first use, keeping Markdown rendering out of the main bundle.
const HelpCenter = lazy(() => import('./components/HelpCenter.jsx'))
const Assistant = lazy(() => import('./components/Assistant.jsx'))

const TABS = [['overview', 'Overview'], ['floor', 'Floor plan'], ['schedule', 'Schedule'], ['workforce', 'Workforce'], ['live', 'Live dispatch'], ['benchmark', 'Benchmark']]
const SLA = { 3: 45, 2: 120, 1: 240 }
const FAB_KEY = 'fab-dispatch-fab'
const TYPING = new Set(['INPUT', 'TEXTAREA', 'SELECT'])

function AlgoSwitch({ results, active, onChange, pending = new Set() }) {
  return (
    <div className="seg" role="group" aria-label="Strategy">
      {ALGO_ORDER.map((a) => {
        const r = results.find((x) => x.algorithm === a)
        return (
          <button key={a} aria-pressed={active === a} onClick={() => onChange(a)} disabled={!r}>
            <span className="swatch" />{ALGO_SHORT[a]}
            {pending.has(a) ? <span className="spinner" aria-label="solving" /> : r && <span className="muted num">{r.metrics.assigned}/{r.metrics.jobs}</span>}
          </button>
        )
      })}
    </div>
  )
}

export default function App() {
  const auth = useAuth()
  const [theme, setTheme] = useState(loadTheme)
  useEffect(() => { applyTheme(theme) }, [theme])
  if (auth.status === 'loading') return <div className="loading"><span className="solving"><span className="spinner" />Loading…</span></div>
  if (auth.status === 'error') return <div className="loading">Can't reach the API ({auth.error}). Is the backend running on port 8000?</div>
  if (auth.status !== 'signedIn') return <SignIn />
  return <Workspace key={auth.user.id} theme={theme} setTheme={setTheme} />
}

function Workspace({ theme, setTheme }) {
  const { canDispatch } = useAuth()
  const [meta, setMeta] = useState(null)
  const [fabs, setFabs] = useState([])
  const [profile, setProfile] = useState(null)
  const [drawer, setDrawer] = useState(false)
  const closeDrawer = useCallback(() => setDrawer(false), [])
  const [params, setParams] = useState({ preset: 'normal', seed: 7, n_engineers: 14, n_jobs: 45 })
  const [scenario, setScenario] = useState(null)
  const [offShift, setOffShift] = useState(() => new Set())
  const [weights, setWeights] = useState(null)
  // Deep links: ?tab=floor opens that view; a shared live-shift link (?shift=…) opens Live dispatch.
  const [tab, setTabState] = useState(() => {
    const q = new URLSearchParams(location.search)
    if (q.has('shift')) return 'live'
    return TABS.some(([k]) => k === q.get('tab')) ? q.get('tab') : 'overview'
  })
  const setTab = (t) => {
    setTabState(t)
    const url = new URL(location.href)
    if (t === 'overview') url.searchParams.delete('tab')
    else url.searchParams.set('tab', t)
    history.replaceState(null, '', url)
  }
  const [active, setActive] = useState('pyvrp')
  const [goal, setGoal] = useState('value')
  const [selection, setSelection] = useState(() => {
    const q = new URLSearchParams(location.search)
    if (q.get('job')) return { type: 'job', id: q.get('job') }
    if (q.get('engineer')) return { type: 'engineer', id: q.get('engineer') }
    return null
  })
  const [floorView, setFloorView] = useState('single')
  const [showChanges, setShowChanges] = useState(true)
  const [addMode, setAddMode] = useState(false)
  const [newJob, setNewJob] = useState({ priority: 3, at: 120 })
  const [error, setError] = useState(null)
  const [predicted, setPredicted] = useState(null) // { original, changes } when history durations are on
  // Help center (null = closed, { slug: null } = home), assistant, and the first-run tour.
  const [help, setHelp] = useState(() => {
    const h = new URLSearchParams(location.search).get('help')
    return h === null ? null : h ? parseHelpTarget(h) : { slug: null, anchor: '' }
  })
  const [askOpen, setAskOpen] = useState(false)
  const [askDraft, setAskDraft] = useState('')
  const [messages, setMessages] = useState([])
  const [touring, setTouring] = useState(false)

  useEffect(() => {
    const url = new URL(location.href)
    url.searchParams.delete('job')
    url.searchParams.delete('engineer')
    if (selection) url.searchParams.set(selection.type, selection.id)
    history.replaceState(null, '', url)
  }, [selection])
  useEffect(() => {
    const url = new URL(location.href)
    if (help) url.searchParams.set('help', help.slug ? `${help.slug}${help.anchor ? `#${help.anchor}` : ''}` : '')
    else url.searchParams.delete('help')
    history.replaceState(null, '', url)
  }, [help])

  const helpApi = useMemo(() => ({
    openHelp: (slug = null, anchor = '') => setHelp({ slug, anchor }),
    openAssistant: (draft = '') => { setAskDraft(draft); setAskOpen(true); setHelp(null) },
  }), [])

  // Keyboard: ? help, / assistant, 1-6 views. Never while typing in a field.
  useEffect(() => {
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey || TYPING.has(e.target.tagName) || e.target.isContentEditable) return
      if (e.key === '?') { e.preventDefault(); setHelp((h) => h ?? { slug: null, anchor: '' }) }
      else if (e.key === '/') { e.preventDefault(); helpApi.openAssistant() }
      else if (/^[1-6]$/.test(e.key) && !help && !askOpen) setTab(TABS[Number(e.key) - 1][0])
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  })

  const regenerate = (p = params, { keepSelection = false, fab = profile } = {}) => {
    setError(null)
    generateScenario({ ...p, fab_id: fab.id })
      .then((s) => { setScenario(s); setOffShift(new Set()); if (!keepSelection) setSelection(null); setPredicted(null) })
      .catch((e) => setError(e.message))
  }

  // Switching fab: everything site-specific (families, floor, shift, presets) comes from its profile.
  const openFab = useCallback(async (fabId, { first = false } = {}) => {
    try {
      const p = await getFab(fabId)
      setActiveFab(p)
      setProfile(p)
      try { localStorage.setItem(FAB_KEY, p.id) } catch { /* private mode */ }
      const url = new URL(location.href)
      url.searchParams.set('fab', p.id)
      history.replaceState(null, '', url)
      setParams((prev) => {
        const next = { ...prev, preset: p.presets[prev.preset] ? prev.preset : Object.keys(p.presets)[0] }
        regenerate(next, { keepSelection: first, fab: p })
        return next
      })
    } catch (e) { setError(e.message) }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    Promise.all([getMeta(), listFabs()]).then(([m, list]) => {
      setMeta(m)
      setWeights(m.default_weights)
      setFabs(list)
      let remembered = null
      try { remembered = localStorage.getItem(FAB_KEY) } catch { /* private mode */ }
      const wanted = [new URLSearchParams(location.search).get('fab'), remembered, m.default_fab]
        .find((id) => id && list.some((f) => f.id === id)) ?? list[0]?.id
      if (!wanted) { setError('Your account has no fabs assigned. Ask an admin for access.'); return }
      // First load keeps a deep-linked ?job= / ?engineer= selection.
      openFab(wanted, { first: true })
    }).catch((e) => setError(e.message))
  }, [openFab])

  const effective = useMemo(() => scenario && ({
    ...scenario, engineers: scenario.engineers.filter((e) => !offShift.has(e.id)),
  }), [scenario, offShift])

  const { results, pending, errors: planErrors, cacheInfo } = usePlans(effective, weights)
  const busy = pending.size > 0
  const reco = results.length ? recommend(results, goal) : null

  // First visit: walk through the workspace once the first plans are on screen.
  useEffect(() => {
    if (!reco || tab !== 'overview') return
    let seen = null
    try { seen = localStorage.getItem(TOUR_KEY) } catch { /* private mode: show it */ }
    if (!seen) setTouring(true)
  }, [Boolean(reco)]) // eslint-disable-line react-hooks/exhaustive-deps
  const endTour = useCallback(() => {
    setTouring(false)
    try { localStorage.setItem(TOUR_KEY, 'done') } catch { /* private mode */ }
  }, [])

  // What the assistant sees: exactly what's on screen.
  const live = useRef({})
  live.current = { profile, effective, weights, tab, active, selection, reco, goal }
  const askContext = useCallback(() => {
    const c = live.current
    return {
      fab_id: c.profile?.id, scenario: c.effective, weights: c.weights, tab: c.tab, active: c.active, selection: c.selection,
      recommendation: c.reco && { algorithm: c.reco.winner.algorithm, why: c.reco.why, goal: c.goal, goal_label: GOALS[c.goal].label, tradeoff: c.reco.tradeoff.join('; ') },
    }
  }, [])
  const suggestions = [
    selection?.type === 'job' && `Why is ${selection.id} assigned this way?`,
    selection?.type === 'engineer' && `What is ${selection.id} doing?`,
    reco && `Why is ${ALGO_SHORT[reco.winner.algorithm]} recommended?`,
    'Which jobs are unassigned?',
    'What does idle wait mean?',
  ].filter(Boolean).slice(0, 4)
  const onAssistantAction = (a) => {
    if (a.kind === 'job' || a.kind === 'engineer') { setSelection({ type: a.kind, id: a.target }); setTab('floor') }
    else if (a.kind === 'strategy') { setActive(a.target); setTab('floor') }
    else if (a.kind === 'tab') setTab(a.target)
    if (window.innerWidth < 640) setAskOpen(false) // the panel covers the view on phones
  }

  const togglePredicted = async (on) => {
    if (!on) {
      setScenario(predicted.original)
      setPredicted(null)
      return
    }
    try {
      const out = await predictDurations(scenario)
      setPredicted({ original: scenario, changes: out.changes })
      setScenario(out.scenario)
    } catch (e) { setError(e.message) }
  }

  const select = (sel) => {
    setSelection(sel)
    if (tab === 'overview' || tab === 'workforce') setTab('floor')
  }
  const toggleEngineer = (id) => setOffShift((prev) => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })
  const addJob = (pt) => {
    const fam = familyAt(pt)
    if (!fam) { setError('Click inside a tool area to report a job there.'); return }
    const n = Math.max(0, ...scenario.jobs.map((j) => parseInt(j.id.slice(1), 10))) + 1
    const p = newJob.priority
    const job = {
      id: `J${String(n).padStart(3, '0')}`, x: pt.x, y: pt.y, skill: fam, min_level: isConstraint(fam) ? 2 : 1,
      priority: p, kind: p === 1 ? 'pm' : 'down', earliest: newJob.at, latest: newJob.at + SLA[p],
      duration: p === 1 ? 120 : 60, tool: `${familyPrefix(fam)}-NEW`,
    }
    setScenario((s) => ({ ...s, jobs: [...s.jobs, job] }))
    setSelection({ type: 'job', id: job.id })
    setError(null)
  }

  if (!meta || !profile || !scenario || !weights || scenario.fab_id !== profile.id) {
    return <div className="loading">{error ? <>{error}</> : <span className="solving"><span className="spinner" />Loading shift…</span>}</div>
  }
  const areas = areasOf(profile)

  const activeResult = results.find((r) => r.algorithm === active) ?? results[results.length - 1]
  const greedy = results.find((r) => r.algorithm === 'greedy')
  const unserved = activeResult?.unassigned.length ?? 0

  return (
    <HelpContext.Provider value={helpApi}>
      <TopBar fabs={fabs} fabId={profile.id} onFab={(id) => openFab(id)} theme={theme} onTheme={setTheme}
        busy={busy} pending={pending} onMenu={() => setDrawer(true)} onHelp={() => helpApi.openHelp()}
        solvedNote={`${results.length} strategies solved${Object.values(cacheInfo).some((c) => c !== 'miss') ? ' · cached' : ''}`}
        chips={<>
          <span className="chip">{profile.presets[params.preset]?.label}</span>
          <span className="chip"><b>{effective.engineers.length}</b> engineers{offShift.size > 0 && ` (${offShift.size} off)`}</span>
          <span className="chip"><b>{scenario.jobs.length}</b> jobs</span>
          <span className="chip"><b>{scenario.jobs.filter((j) => j.priority === 3).length}</b> bottleneck downs</span>
        </>} />

      <div className="layout">
        <Sidebar open={drawer} onClose={closeDrawer} profile={profile} params={params} setParams={setParams}
          onGenerate={() => regenerate()} weights={weights} setWeights={setWeights} defaultWeights={meta.default_weights}
          addMode={addMode} setAddMode={(v) => { setAddMode(v); if (v) setTab('floor') }} newJob={newJob} setNewJob={setNewJob}
          predicted={predicted} onTogglePredicted={togglePredicted} offShiftCount={offShift.size} onRestoreAll={() => setOffShift(new Set())} />

        <main className="content">
          {error && <div className="error-bar" role="alert">{error} <button className="btn ghost" onClick={() => setError(null)}>Dismiss</button></div>}
          {Object.entries(planErrors).map(([a, msg]) => <div key={a} className="error-bar" role="alert">{ALGO_SHORT[a]}: {msg}</div>)}
          <nav className="nav" role="tablist" aria-label="Views" data-tour="tabs">
            {TABS.map(([k, label], i) => (
              <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>
                <span className="idx">{String(i + 1).padStart(2, '0')}</span>{label}{k === 'workforce' && unserved > 0 && <span className="count">{unserved}</span>}
              </button>
            ))}
          </nav>

          {tab === 'live' ? <LiveShift scenario={effective} weights={weights} areas={areas} profile={profile} canDispatch={canDispatch} onError={setError} /> : results.length === 0 ? <div className="card empty"><span className="solving"><span className="spinner" />Solving the shift…</span></div> : (
            <>
              {tab === 'overview' && (
                <Overview results={results} pending={pending} scenario={scenario} goal={goal} onGoal={setGoal}
                  onPickAlgo={(a) => { setActive(a); setTab('floor') }} onSelect={select} />
              )}

              {tab === 'floor' && (
                <div className="floor-layout">
                  <section className="card">
                    <div className="floor-toolbar">
                      <AlgoSwitch results={results} active={active} onChange={setActive} pending={pending} />
                      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                        {floorView === 'single' && active !== 'greedy' && (
                          <label className="toggle"><input type="checkbox" checked={showChanges} onChange={(e) => setShowChanges(e.target.checked)} />Coverage changes vs Greedy</label>
                        )}
                        <div className="seg" role="group" aria-label="Layout">
                          <button aria-pressed={floorView === 'single'} onClick={() => setFloorView('single')}>Single</button>
                          <button aria-pressed={floorView === 'side'} onClick={() => setFloorView('side')}>Side by side</button>
                        </div>
                      </div>
                    </div>
                    {floorView === 'single' ? (
                      <div className="floor-wrap">
                        <FloorPlan scenario={scenario} result={activeResult} baseline={active !== 'greedy' ? greedy : null}
                          areas={areas} selection={selection} onSelect={setSelection} offShift={offShift}
                          onToggleEngineer={toggleEngineer} addMode={addMode} onFloorClick={addJob} showChanges={showChanges} />
                      </div>
                    ) : (
                      <div className="floor-wrap cards" style={{ gap: 12, gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
                        {ALGO_ORDER.map((a) => {
                          const r = results.find((x) => x.algorithm === a)
                          if (!r) return <div key={a} className="skeleton" style={{ minHeight: 180 }} />
                          return (
                            <figure key={a} style={{ margin: 0 }}>
                              <figcaption style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, marginBottom: 6 }}>
                                <span className="swatch" /><b>{ALGO_SHORT[a]}</b>
                                <span className="muted num">{r.metrics.assigned}/{r.metrics.jobs} jobs · cost {r.metrics.objective}</span>
                              </figcaption>
                              <FloorPlan compact scenario={scenario} result={r} areas={areas} selection={selection} onSelect={setSelection} offShift={offShift} />
                            </figure>
                          )
                        })}
                      </div>
                    )}
                    <div className="legend-row" aria-label="Legend">
                      <span><i className="lg eng" />Engineer, home bay</span>
                      <span><i className="lg circle o3" />Bottleneck down</span>
                      <span><i className="lg circle o2" />Tool down</span>
                      <span><i className="lg o1" style={{ borderRadius: 2 }} />PM</span>
                      <span><i className="lg un" />Unassigned</span>
                      {showChanges && active !== 'greedy' && floorView === 'single' && <span><i className="lg chg" />Served here but not by Greedy (or the reverse)</span>}
                      <span><i className="lg route" />Route in focus (hover any job)</span>
                    </div>
                  </section>
                  <Inspector selection={selection} scenario={scenario} results={results} active={active}
                    offShift={offShift} onToggleEngineer={toggleEngineer} onSelect={setSelection} />
                </div>
              )}

              {tab === 'schedule' && activeResult && (
                <div className="floor-layout">
                  <section className="card">
                    <div className="floor-toolbar">
                      <AlgoSwitch results={results} active={active} onChange={setActive} pending={pending} />
                      <div className="legend-row" style={{ padding: 0 }}>
                        <span><i className="lg o3" style={{ borderRadius: 3 }} />Bottleneck</span>
                        <span><i className="lg o2" style={{ borderRadius: 3 }} />Tool down</span>
                        <span><i className="lg o1" style={{ borderRadius: 3 }} />PM</span>
                        <span><i className="lg" style={{ height: 2, width: 14, background: 'var(--line-2)' }} />Walking</span>
                        <span><i className="lg" style={{ height: 2, width: 14, background: 'repeating-linear-gradient(90deg, var(--ink-3) 0 2px, transparent 2px 5px)' }} />Idle wait</span>
                      </div>
                    </div>
                    <Schedule scenario={scenario} result={activeResult} selection={selection} onSelect={setSelection} offShift={offShift} />
                  </section>
                  <Inspector selection={selection} scenario={scenario} results={results} active={active}
                    offShift={offShift} onToggleEngineer={toggleEngineer} onSelect={setSelection} />
                </div>
              )}

              {tab === 'workforce' && activeResult && (
                <>
                  <div><AlgoSwitch results={results} active={active} onChange={setActive} pending={pending} /></div>
                  <Workforce scenario={scenario} result={activeResult} offShift={offShift} onSelect={select} />
                  {activeResult.unassigned.length > 0 && (
                    <section className="card">
                      <div className="card-h"><div><h2>Unserved work · {activeResult.label}</h2><p>Why each job could not be placed.</p></div></div>
                      <div className="card-b table-wrap">
                        <table className="data">
                          <thead><tr><th>Job</th><th>Type</th><th>Needs</th><th>Reason</th></tr></thead>
                          <tbody>
                            {activeResult.unassigned.map((u) => {
                              const j = scenario.jobs.find((x) => x.id === u.job_id)
                              return (
                                <tr key={u.job_id} onClick={() => select({ type: 'job', id: u.job_id })}>
                                  <td><b>{u.job_id}</b> <span className="muted">{j.tool}</span></td>
                                  <td><span className={`badge p${j.priority}`}>{PRIORITY[j.priority].label}</span></td>
                                  <td>{familyLabel(j.skill)} L{j.min_level}+</td>
                                  <td>{u.reason}</td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                      </div>
                    </section>
                  )}
                </>
              )}

              {tab === 'benchmark' && <Benchmark profile={profile} weights={weights} size={params} canDispatch={canDispatch} />}
            </>
          )}
        </main>
      </div>

      {!askOpen && <button className="ask-fab" data-tour="ask" onClick={() => helpApi.openAssistant()} aria-label="Ask the assistant" aria-keyshortcuts="/"><span className="dot" />Ask</button>}
      <Suspense fallback={null}>
        {askOpen && <Assistant messages={messages} setMessages={setMessages} context={askContext} suggestions={suggestions}
          draft={askDraft} onAction={onAssistantAction} onClose={() => setAskOpen(false)} />}
        {help && <HelpCenter target={help} onNavigate={(slug, anchor = '') => setHelp({ slug, anchor })} onClose={() => setHelp(null)}
          onTour={() => { setHelp(null); setTab('overview'); setTouring(true) }} />}
      </Suspense>
      {touring && results.length > 0 && tab === 'overview' && <Tour onDone={endTour} />}
    </HelpContext.Provider>
  )
}
