import { useEffect } from 'react'
import { PRIORITY } from '../lib/format.js'
import { shiftLength } from '../lib/fab.js'
import InfoLink from './InfoLink.jsx'

const WEIGHTS = [
  ['priority_reward', 'Priority reward', 'per priority point served', 0, 200, 5],
  ['travel_100m', 'Walking', 'per 100 m', 0, 20, 0.5],
  ['wait_min', 'Idle wait', 'per minute', 0, 2, 0.05],
  ['overqualification', 'Over-qualification', 'per level above need', 0, 40, 1],
  ['workload_balance', 'Workload balance', 'per job already held', 0, 30, 1],
]

/** Scenario, cost weights and what-ifs. A column on desktop, a drawer on small screens. */
export default function Sidebar({
  open, onClose, profile, params, setParams, onGenerate, weights, setWeights, defaultWeights,
  addMode, setAddMode, newJob, setNewJob, predicted, onTogglePredicted, offShiftCount, onRestoreAll,
}) {
  useEffect(() => {
    if (!open) return
    const esc = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [open, onClose])

  const preset = profile.presets[params.preset] ?? Object.values(profile.presets)[0]
  return (
    <>
      {open && <div className="backdrop" onClick={onClose} aria-hidden />}
      <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="Controls">
        <div className="drawer-h"><b>Controls</b><button className="btn ghost" onClick={onClose} aria-label="Close controls">✕</button></div>
        <section className="card card-b">
          <p className="eyebrow">Shift scenario <InfoLink slug="what-ifs" anchor="generate-a-shift" label="Generating shifts" /></p>
          <label className="field"><span>Preset</span>
            <select className="input" value={params.preset} onChange={(e) => setParams({ ...params, preset: e.target.value })}>
              {Object.entries(profile.presets).map(([k, p]) => <option key={k} value={k}>{p.label}</option>)}
            </select>
          </label>
          <p className="help">{preset.description}</p>
          <div className="row-3">
            <label className="field"><span>Seed</span><input className="input" type="number" inputMode="numeric" value={params.seed} onChange={(e) => setParams({ ...params, seed: +e.target.value })} /></label>
            <label className="field"><span>Engineers</span><input className="input" type="number" inputMode="numeric" min={1} max={60} value={params.n_engineers} onChange={(e) => setParams({ ...params, n_engineers: +e.target.value })} /></label>
            <label className="field"><span>Jobs</span><input className="input" type="number" inputMode="numeric" min={1} max={200} value={params.n_jobs} onChange={(e) => setParams({ ...params, n_jobs: +e.target.value })} /></label>
          </div>
          <button className="btn primary block" onClick={() => { onGenerate(); onClose() }}>Generate shift</button>
        </section>

        <details className="card card-b section" open data-tour="weights">
          <summary><p className="eyebrow" style={{ margin: 0 }}>Cost weights <InfoLink slug="constraints-and-weights" anchor="soft-constraints-the-cost-weights" label="Cost weights" /></p></summary>
          <p className="help" style={{ marginTop: 8 }}>Soft constraints. Every strategy re-solves as you drag.</p>
          {WEIGHTS.map(([key, label, unit, min, max, step]) => (
            <label key={key} className="field">
              <span>{label} <span className="muted">{unit}</span><b>{weights[key]}</b></span>
              <input type="range" min={min} max={max} step={step} value={weights[key]}
                onChange={(e) => setWeights({ ...weights, [key]: +e.target.value })} aria-label={label} />
            </label>
          ))}
          <button className="btn block" onClick={() => setWeights(defaultWeights)}>Reset to defaults</button>
        </details>

        <details className="card card-b section" open>
          <summary><p className="eyebrow" style={{ margin: 0 }}>What-if <InfoLink slug="what-ifs" label="What-if scenarios" /></p></summary>
          <label className="toggle" style={{ marginTop: 10 }}>
            <input type="checkbox" checked={addMode} onChange={(e) => { setAddMode(e.target.checked); if (e.target.checked) onClose() }} />
            Report a job by tapping the floor
          </label>
          {addMode && (
            <div className="row-3" style={{ gridTemplateColumns: '1fr 1fr', marginTop: 10 }}>
              <label className="field"><span>Type</span>
                <select className="input" value={newJob.priority} onChange={(e) => setNewJob({ ...newJob, priority: +e.target.value })}>
                  {[3, 2, 1].map((p) => <option key={p} value={p}>{PRIORITY[p].long}</option>)}
                </select>
              </label>
              <label className="field"><span>Reported (min)</span>
                <input className="input" type="number" inputMode="numeric" min={0} max={shiftLength() - 60} value={newJob.at} onChange={(e) => setNewJob({ ...newJob, at: +e.target.value })} />
              </label>
            </div>
          )}
          <label className="toggle" style={{ marginTop: 12 }}>
            <input type="checkbox" checked={Boolean(predicted)} onChange={(e) => onTogglePredicted(e.target.checked)} />
            Plan with history-predicted durations
          </label>
          <p className="help" style={{ marginTop: 4 }}>
            {predicted ? `${predicted.changes.filter((c) => c.predicted !== c.standard).length} tool-down durations replaced by the repair-history prediction.`
              : "Swap each tool-down's standard estimate for what similar past repairs actually took."}
          </p>
          <p className="help" style={{ marginTop: 10 }}>Select an engineer to take them off shift (sick call, training) and see who absorbs their work.</p>
          {offShiftCount > 0 && <button className="btn block" onClick={onRestoreAll}>Restore all {offShiftCount} engineers</button>}
        </details>
      </aside>
    </>
  )
}
