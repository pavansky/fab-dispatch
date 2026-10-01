import { useEffect, useMemo, useState } from 'react'
import { allocate, generateScenario, getMeta } from './api.js'
import FloorPlan from './components/FloorPlan.jsx'
import Comparison from './components/Comparison.jsx'
import Timeline from './components/Timeline.jsx'
import JobDetail from './components/JobDetail.jsx'
import { FAMILY_COLORS, PRIORITY_LABEL } from './theme.js'

const WEIGHT_UI = [
  ['travel_100m', 'Walking (per 100 m)', 0, 20, 0.5],
  ['wait_min', 'Idle wait (per min)', 0, 2, 0.05],
  ['overqualification', 'Over-qualification (per level)', 0, 40, 1],
  ['workload_balance', 'Workload balance (per job held)', 0, 30, 1],
  ['priority_reward', 'Priority reward (per point)', 0, 200, 5],
]

function familyAt(areas, { x, y }) {
  return Object.entries(areas).find(([, [x0, y0, x1, y1]]) => x >= x0 && x <= x1 && y >= y0 && y <= y1)?.[0]
}

export default function App() {
  const [meta, setMeta] = useState(null)
  const [params, setParams] = useState({ preset: 'normal', seed: 7, n_engineers: 14, n_jobs: 45 })
  const [scenario, setScenario] = useState(null)
  const [offShift, setOffShift] = useState(new Set())
  const [weights, setWeights] = useState(null)
  const [results, setResults] = useState([])
  const [active, setActive] = useState('hungarian')
  const [view, setView] = useState('single')
  const [selectedJob, setSelectedJob] = useState(null)
  const [addMode, setAddMode] = useState(false)
  const [newPriority, setNewPriority] = useState(3)
  const [newAt, setNewAt] = useState(120)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getMeta().then((m) => { setMeta(m); setWeights(m.default_weights) }).catch((e) => setError(e.message))
  }, [])

  const regenerate = () => {
    setError(null)
    generateScenario(params)
      .then((s) => { setScenario(s); setOffShift(new Set()); setSelectedJob(null) })
      .catch((e) => setError(e.message))
  }
  useEffect(regenerate, []) // eslint-disable-line react-hooks/exhaustive-deps

  const effective = useMemo(() => scenario && {
    ...scenario, engineers: scenario.engineers.filter((e) => !offShift.has(e.id)),
  }, [scenario, offShift])

  useEffect(() => {
    if (!effective || !weights) return
    const id = setTimeout(() => {
      setBusy(true)
      allocate(effective, weights)
        .then((r) => { setResults(r); setError(null) })
        .catch((e) => setError(e.message))
        .finally(() => setBusy(false))
    }, 200)
    return () => clearTimeout(id)
  }, [effective, weights])

  const activeResult = results.find((r) => r.algorithm === active)
  const job = scenario?.jobs.find((j) => j.id === selectedJob)

  const toggleEngineer = (id) => setOffShift((prev) => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })

  const addJob = (pt) => {
    const fam = familyAt(meta.areas, pt)
    if (!fam) { setError('Click inside a tool area to report a job there.'); return }
    const n = Math.max(0, ...scenario.jobs.map((j) => parseInt(j.id.slice(1), 10))) + 1
    const sla = newPriority === 3 ? 45 : newPriority === 2 ? 120 : 240
    const j = {
      id: `J${String(n).padStart(3, '0')}`, x: pt.x, y: pt.y, skill: fam,
      min_level: fam === 'litho' ? 2 : 1, priority: newPriority, kind: newPriority === 1 ? 'pm' : 'down',
      earliest: newAt, latest: newAt + sla, duration: newPriority === 1 ? 120 : 60, tool: `${fam.slice(0, 3).toUpperCase()}-NEW`,
    }
    setScenario((s) => ({ ...s, jobs: [...s.jobs, j] }))
    setSelectedJob(j.id)
    setError(null)
  }

  if (!meta || !scenario || !weights) {
    return <div className="loading">{error ? `Can't reach the API: ${error}. Is the backend running on :8000?` : 'Loading…'}</div>
  }

  return (
    <div className="app">
      <header>
        <div>
          <h1>Fab Maintenance Dispatch</h1>
          <p className="tagline">Assigning equipment engineers to tool-downs and PMs across a 300mm fab floor, compared across three allocation strategies.</p>
        </div>
        <span className={`status ${busy ? 'busy' : ''}`}>{busy ? 'Solving…' : `${results.length} algorithms solved`}</span>
      </header>

      <aside className="panel controls">
        <section>
          <h2>Scenario</h2>
          <label>Preset
            <select value={params.preset} onChange={(e) => setParams({ ...params, preset: e.target.value })}>
              {Object.entries(meta.presets).map(([k, p]) => <option key={k} value={k}>{p.label}</option>)}
            </select>
          </label>
          <p className="hint">{meta.presets[params.preset].description}</p>
          <div className="row2">
            <label>Seed<input type="number" value={params.seed} onChange={(e) => setParams({ ...params, seed: +e.target.value })} /></label>
            <label>Engineers<input type="number" min={1} max={60} value={params.n_engineers} onChange={(e) => setParams({ ...params, n_engineers: +e.target.value })} /></label>
            <label>Jobs<input type="number" min={1} max={200} value={params.n_jobs} onChange={(e) => setParams({ ...params, n_jobs: +e.target.value })} /></label>
          </div>
          <button className="primary" onClick={regenerate}>Generate shift</button>
        </section>

        <section>
          <h2>Soft-constraint weights</h2>
          {WEIGHT_UI.map(([key, label, min, max, step]) => (
            <label key={key} className="slider">
              <span>{label}<b>{weights[key]}</b></span>
              <input type="range" min={min} max={max} step={step} value={weights[key]}
                onChange={(e) => setWeights({ ...weights, [key]: +e.target.value })} />
            </label>
          ))}
          <button onClick={() => setWeights(meta.default_weights)}>Reset weights</button>
        </section>

        <section>
          <h2>What-if</h2>
          <label className="check">
            <input type="checkbox" checked={addMode} onChange={(e) => setAddMode(e.target.checked)} />
            Click the floor to report a new job
          </label>
          {addMode && (
            <div className="row2">
              <label>Type
                <select value={newPriority} onChange={(e) => setNewPriority(+e.target.value)}>
                  {[3, 2, 1].map((p) => <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>)}
                </select>
              </label>
              <label>Reported at (min)<input type="number" min={0} max={660} value={newAt} onChange={(e) => setNewAt(+e.target.value)} /></label>
            </div>
          )}
          <p className="hint">Click an engineer square to send them off shift (sick call, training). {offShift.size > 0 && <b>{offShift.size} off shift.</b>}</p>
        </section>

        <section className="legend">
          <h2>Legend</h2>
          <div><span className="sw sq" /> Engineer (home bay)</div>
          <div><span className="sw dot" /> Job, coloured by engineer</div>
          <div><span className="sw ring" /> Bottleneck tool-down</div>
          <div><span className="sw open" /> Unassigned</div>
          <div className="fams">{Object.entries(FAMILY_COLORS).map(([f, c]) => <span key={f}><i style={{ background: c }} />{f}</span>)}</div>
        </section>
      </aside>

      <main>
        {error && <div className="error">{error}</div>}
        <div className="panel">
          <div className="toolbar">
            <div className="tabs" role="tablist">
              {results.map((r) => (
                <button key={r.algorithm} role="tab" aria-selected={active === r.algorithm}
                  className={active === r.algorithm ? 'on' : ''} onClick={() => setActive(r.algorithm)}>
                  {r.label}<small>{r.metrics.assigned}/{r.metrics.jobs}</small>
                </button>
              ))}
            </div>
            <div className="tabs">
              <button className={view === 'single' ? 'on' : ''} onClick={() => setView('single')}>Single</button>
              <button className={view === 'side' ? 'on' : ''} onClick={() => setView('side')}>Side by side</button>
            </div>
          </div>
          {view === 'single' ? (
            <FloorPlan scenario={scenario} result={activeResult} areas={meta.areas} selectedJob={selectedJob}
              onSelectJob={setSelectedJob} offShift={offShift} onToggleEngineer={toggleEngineer}
              onFloorClick={addJob} addMode={addMode} />
          ) : (
            <div className="side">
              {results.map((r) => (
                <figure key={r.algorithm}>
                  <figcaption>{r.label} · {r.metrics.assigned}/{r.metrics.jobs} jobs · objective {r.metrics.objective}</figcaption>
                  <FloorPlan compact scenario={scenario} result={r} areas={meta.areas} selectedJob={selectedJob}
                    onSelectJob={setSelectedJob} offShift={offShift} />
                </figure>
              ))}
            </div>
          )}
        </div>

        <div className="grid2">
          <div className="panel">
            <h2>Algorithm comparison</h2>
            <Comparison results={results} active={active} onSelect={setActive} />
          </div>
          <div className="panel">
            <h2>Decision explanation</h2>
            <JobDetail job={job} results={results} active={active} />
          </div>
        </div>

        {activeResult && (
          <div className="panel">
            <h2>Shift schedule · {activeResult.label}</h2>
            <Timeline scenario={effective} result={activeResult} selectedJob={selectedJob} onSelectJob={setSelectedJob} />
          </div>
        )}

        {activeResult?.unassigned.length > 0 && (
          <div className="panel">
            <h2>Unassigned · {activeResult.label} ({activeResult.unassigned.length})</h2>
            <ul className="unassigned">
              {activeResult.unassigned.map((u) => {
                const j = scenario.jobs.find((x) => x.id === u.job_id)
                return (
                  <li key={u.job_id}>
                    <button className="linklike" onClick={() => setSelectedJob(u.job_id)}>{u.job_id}</button>
                    <span className={`pill p${j.priority}`}>{PRIORITY_LABEL[j.priority]}</span> {j.tool} ({j.skill} L{j.min_level}): {u.reason}
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </main>
    </div>
  )
}
