import { useEffect, useMemo, useState } from 'react'
import { generateScenario, getMeta, predictDurations } from './api.js'
import { usePlans } from './lib/usePlans.js'
import { applyTheme, loadTheme } from './lib/theme.js'
import { ALGO_ORDER, ALGO_SHORT } from './lib/metrics.js'
import { FAMILY_LABEL, PRIORITY } from './lib/format.js'
import FloorPlan from './components/FloorPlan.jsx'
import Inspector from './components/Inspector.jsx'
import Overview from './components/Overview.jsx'
import Schedule from './components/Schedule.jsx'
import Workforce from './components/Workforce.jsx'
import Benchmark from './components/Benchmark.jsx'
import LiveShift from './components/LiveShift.jsx'

const WEIGHTS = [
  ['priority_reward', 'Priority reward', 'per priority point served', 0, 200, 5],
  ['travel_100m', 'Walking', 'per 100 m', 0, 20, 0.5],
  ['wait_min', 'Idle wait', 'per minute', 0, 2, 0.05],
  ['overqualification', 'Over-qualification', 'per level above need', 0, 40, 1],
  ['workload_balance', 'Workload balance', 'per job already held', 0, 30, 1],
]
const TABS = [['overview', 'Overview'], ['floor', 'Floor plan'], ['schedule', 'Schedule'], ['workforce', 'Workforce'], ['live', 'Live dispatch'], ['benchmark', 'Benchmark']]
const SLA = { 3: 45, 2: 120, 1: 240 }

const familyAt = (areas, { x, y }) =>
  Object.entries(areas).find(([, [x0, y0, x1, y1]]) => x >= x0 && x <= x1 && y >= y0 && y <= y1)?.[0]

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
  const [meta, setMeta] = useState(null)
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
  const [theme, setTheme] = useState(loadTheme)
  const [error, setError] = useState(null)
  const [predicted, setPredicted] = useState(null) // { original, changes } when history durations are on

  useEffect(() => { applyTheme(theme) }, [theme])
  useEffect(() => {
    const url = new URL(location.href)
    url.searchParams.delete('job')
    url.searchParams.delete('engineer')
    if (selection) url.searchParams.set(selection.type, selection.id)
    history.replaceState(null, '', url)
  }, [selection])
  useEffect(() => {
    getMeta().then((m) => { setMeta(m); setWeights(m.default_weights) }).catch((e) => setError(e.message))
  }, [])

  const regenerate = (p = params, { keepSelection = false } = {}) => {
    setError(null)
    generateScenario(p)
      .then((s) => { setScenario(s); setOffShift(new Set()); if (!keepSelection) setSelection(null); setPredicted(null) })
      .catch((e) => setError(e.message))
  }
  // First load keeps a deep-linked ?job= / ?engineer= selection; later regenerations clear it.
  useEffect(() => { regenerate(params, { keepSelection: true }) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const effective = useMemo(() => scenario && ({
    ...scenario, engineers: scenario.engineers.filter((e) => !offShift.has(e.id)),
  }), [scenario, offShift])

  const { results, pending, errors: planErrors, cacheInfo } = usePlans(effective, weights)
  const busy = pending.size > 0

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
    const fam = familyAt(meta.areas, pt)
    if (!fam) { setError('Click inside a tool area to report a job there.'); return }
    const n = Math.max(0, ...scenario.jobs.map((j) => parseInt(j.id.slice(1), 10))) + 1
    const p = newJob.priority
    const job = {
      id: `J${String(n).padStart(3, '0')}`, x: pt.x, y: pt.y, skill: fam, min_level: fam === 'litho' ? 2 : 1,
      priority: p, kind: p === 1 ? 'pm' : 'down', earliest: newJob.at, latest: newJob.at + SLA[p],
      duration: p === 1 ? 120 : 60, tool: `${fam.slice(0, 3).toUpperCase()}-NEW`,
    }
    setScenario((s) => ({ ...s, jobs: [...s.jobs, job] }))
    setSelection({ type: 'job', id: job.id })
    setError(null)
  }

  if (!meta || !scenario || !weights) {
    return <div className="loading">{error ? <>Can't reach the API ({error}). Is the backend running on port 8000?</> : 'Loading shift…'}</div>
  }

  const activeResult = results.find((r) => r.algorithm === active) ?? results[results.length - 1]
  const greedy = results.find((r) => r.algorithm === 'greedy')
  const unserved = activeResult?.unassigned.length ?? 0

  return (
    <>
      <header className="topbar">
        <div className="brand"><span className="brand-mark"><span /></span>Fab Dispatch<small>/ allocation engine</small></div>
        <div className="context" aria-label="Current scenario">
          <span className="chip">{meta.presets[params.preset].label}</span>
          <span className="chip"><b>{effective.engineers.length}</b> engineers{offShift.size > 0 && ` (${offShift.size} off)`}</span>
          <span className="chip"><b>{scenario.jobs.length}</b> jobs</span>
          <span className="chip"><b>{scenario.jobs.filter((j) => j.priority === 3).length}</b> bottleneck downs</span>
          <span className="chip">seed {params.seed}</span>
        </div>
        <span className="spacer" />
        <span className="solve-state" aria-live="polite"><span className={`dot ${busy ? 'busy' : ''}`} />
          {busy ? `Solving ${[...pending].map((a) => ALGO_SHORT[a]).join(', ')}…`
            : `${results.length} strategies solved${Object.values(cacheInfo).some((c) => c !== 'miss') ? ' · cached' : ''}`}</span>
        <div className="seg" role="group" aria-label="Theme">
          {['system', 'light', 'dark'].map((m) => (
            <button key={m} aria-pressed={theme === m} onClick={() => setTheme(m)}>{m[0].toUpperCase() + m.slice(1)}</button>
          ))}
        </div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <section className="card card-b">
            <p className="eyebrow">Shift scenario</p>
            <label className="field"><span>Preset</span>
              <select className="input" value={params.preset} onChange={(e) => setParams({ ...params, preset: e.target.value })}>
                {Object.entries(meta.presets).map(([k, p]) => <option key={k} value={k}>{p.label}</option>)}
              </select>
            </label>
            <p className="help">{meta.presets[params.preset].description}</p>
            <div className="row-3">
              <label className="field"><span>Seed</span><input className="input" type="number" value={params.seed} onChange={(e) => setParams({ ...params, seed: +e.target.value })} /></label>
              <label className="field"><span>Engineers</span><input className="input" type="number" min={1} max={60} value={params.n_engineers} onChange={(e) => setParams({ ...params, n_engineers: +e.target.value })} /></label>
              <label className="field"><span>Jobs</span><input className="input" type="number" min={1} max={200} value={params.n_jobs} onChange={(e) => setParams({ ...params, n_jobs: +e.target.value })} /></label>
            </div>
            <button className="btn primary block" onClick={() => regenerate()}>Generate shift</button>
          </section>

          <details className="card card-b section" open>
            <summary><p className="eyebrow" style={{ margin: 0 }}>Cost weights</p></summary>
            <p className="help" style={{ marginTop: 8 }}>Soft constraints. Every strategy re-solves as you drag.</p>
            {WEIGHTS.map(([key, label, unit, min, max, step]) => (
              <label key={key} className="field">
                <span>{label} <span className="muted">{unit}</span><b>{weights[key]}</b></span>
                <input type="range" min={min} max={max} step={step} value={weights[key]}
                  onChange={(e) => setWeights({ ...weights, [key]: +e.target.value })} aria-label={label} />
              </label>
            ))}
            <button className="btn block" onClick={() => setWeights(meta.default_weights)}>Reset to defaults</button>
          </details>

          <details className="card card-b section" open>
            <summary><p className="eyebrow" style={{ margin: 0 }}>What-if</p></summary>
            <label className="toggle" style={{ marginTop: 10 }}>
              <input type="checkbox" checked={addMode} onChange={(e) => { setAddMode(e.target.checked); if (e.target.checked) setTab('floor') }} />
              Report a job by clicking the floor
            </label>
            {addMode && (
              <div className="row-3" style={{ gridTemplateColumns: '1fr 1fr', marginTop: 10 }}>
                <label className="field"><span>Type</span>
                  <select className="input" value={newJob.priority} onChange={(e) => setNewJob({ ...newJob, priority: +e.target.value })}>
                    {[3, 2, 1].map((p) => <option key={p} value={p}>{PRIORITY[p].long}</option>)}
                  </select>
                </label>
                <label className="field"><span>Reported (min)</span>
                  <input className="input" type="number" min={0} max={660} value={newJob.at} onChange={(e) => setNewJob({ ...newJob, at: +e.target.value })} />
                </label>
              </div>
            )}
            <label className="toggle" style={{ marginTop: 12 }}>
              <input type="checkbox" checked={Boolean(predicted)} onChange={(e) => togglePredicted(e.target.checked)} />
              Plan with history-predicted durations
            </label>
            <p className="help" style={{ marginTop: 4 }}>
              {predicted ? `${predicted.changes.filter((c) => c.predicted !== c.standard).length} tool-down durations replaced by the repair-history prediction (Qdrant nearest neighbours).`
                : 'Swap each tool-down\'s standard estimate for what similar past repairs actually took.'}
            </p>
            <p className="help" style={{ marginTop: 10 }}>Select an engineer to take them off shift (sick call, training) and see who absorbs their work.</p>
            {offShift.size > 0 && <button className="btn block" onClick={() => setOffShift(new Set())}>Restore all {offShift.size} engineers</button>}
          </details>
        </aside>

        <main className="content">
          {error && <div className="error-bar" role="alert">{error} <button className="btn ghost" onClick={() => setError(null)}>Dismiss</button></div>}
          {Object.entries(planErrors).map(([a, msg]) => <div key={a} className="error-bar" role="alert">{ALGO_SHORT[a]}: {msg}</div>)}
          <nav className="nav" role="tablist">
            {TABS.map(([k, label], i) => (
              <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>
                <span className="idx">{String(i + 1).padStart(2, '0')}</span>{label}{k === 'workforce' && unserved > 0 && <span className="count">{unserved}</span>}
              </button>
            ))}
          </nav>

          {tab === 'live' ? <LiveShift scenario={effective} weights={weights} areas={meta.areas} onError={setError} /> : results.length === 0 ? <div className="card empty"><span className="solving"><span className="spinner" />Solving the shift…</span></div> : (
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
                          areas={meta.areas} selection={selection} onSelect={setSelection} offShift={offShift}
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
                              <FloorPlan compact scenario={scenario} result={r} areas={meta.areas} selection={selection} onSelect={setSelection} offShift={offShift} />
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
                                  <td>{FAMILY_LABEL[j.skill]} L{j.min_level}+</td>
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

              {tab === 'benchmark' && <Benchmark meta={meta} weights={weights} size={params} />}
            </>
          )}
        </main>
      </div>
    </>
  )
}
