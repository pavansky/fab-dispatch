import { ALGO_ORDER, ALGO_SHORT } from '../lib/metrics.js'
import { FAMILY_LABEL, PRIORITY, REJECTION_LABEL, clock, fmt } from '../lib/format.js'

function JobView({ job, results, active, onSelect }) {
  return (
    <>
      <div className="insp-h">
        <p className="eyebrow">Job</p>
        <h3>{job.id} <span className="muted" style={{ fontWeight: 400 }}>{job.tool}</span>
          <span className={`badge p${job.priority}`}>{PRIORITY[job.priority].label}</span></h3>
        <dl className="facts">
          <dt>Needs</dt><dd>{FAMILY_LABEL[job.skill]}, level {job.min_level}+</dd>
          <dt>Start window</dt><dd className="num">{clock(job.earliest)} – {clock(job.latest)} ({job.latest - job.earliest} min)</dd>
          <dt>Duration</dt><dd className="num">{job.duration} min</dd>
          <dt>Floor position</dt><dd className="num">{fmt(job.x, 0)} m E, {fmt(job.y, 0)} m N</dd>
        </dl>
      </div>
      {ALGO_ORDER.map((key) => {
        const r = results.find((x) => x.algorithm === key)
        if (!r) return null
        const a = r.assignments.find((x) => x.job_id === job.id)
        const u = r.unassigned.find((x) => x.job_id === job.id)
        return (
          <div key={key} className={`decision ${key === active ? 'active' : ''}`}>
            <div className="decision-h">
              <span className={`swatch sw-${key}`} />{ALGO_SHORT[key]}
              <span className="who">
                {a ? <button className="btn ghost" style={{ padding: '0 4px' }} onClick={() => onSelect({ type: 'engineer', id: a.tech_id })}>{a.tech_id} →</button>
                  : <span className="cell-none">Unassigned</span>}
              </span>
            </div>
            {a && (
              <>
                <p>{a.explanation}</p>
                <div className="costs">
                  <span>starts {clock(a.start)}</span>
                  {Object.entries(a.cost_breakdown).map(([k, v]) => (
                    <span key={k} className={v < 0 ? 'neg' : ''}>{k} {v > 0 ? '+' : ''}{fmt(v)}</span>
                  ))}
                </div>
              </>
            )}
            {u && (
              <>
                <p>{u.reason}</p>
                <div className="costs">
                  {Object.entries(u.rejections).map(([k, v]) => <span key={k}>{v}× {REJECTION_LABEL[k] ?? k}</span>)}
                </div>
              </>
            )}
          </div>
        )
      })}
    </>
  )
}

function EngineerView({ eng, result, scenario, offShift, onToggleEngineer, onSelect }) {
  const route = result?.routes.find((r) => r.tech_id === eng.id)
  const jobs = Object.fromEntries(scenario.jobs.map((j) => [j.id, j]))
  const busy = route?.stops.reduce((s, x) => s + (x.end - x.start), 0) ?? 0
  const off = offShift.has(eng.id)
  return (
    <>
      <div className="insp-h">
        <p className="eyebrow">Engineer</p>
        <h3>{eng.id} <span style={{ fontWeight: 400 }}>{eng.name}</span>{off && <span className="badge">Off shift</span>}</h3>
        <div className="skills">
          {Object.entries(eng.skills).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
            <span key={k} className={`lvl l${v}`}>{FAMILY_LABEL[k]} L{v}</span>
          ))}
        </div>
        <dl className="facts">
          <dt>Shift</dt><dd className="num">{clock(eng.shift_start)} – {clock(eng.shift_end)}</dd>
          <dt>Jobs</dt><dd className="num">{route?.stops.length ?? 0} of max {eng.max_jobs}</dd>
          <dt>Hands-on time</dt><dd className="num">{fmt(busy / 60)} h ({Math.round((busy / (eng.shift_end - eng.shift_start)) * 100)}%)</dd>
          <dt>Walking</dt><dd className="num">{fmt(route?.metres ?? 0, 0)} m</dd>
        </dl>
        <button className="btn" style={{ marginTop: 12 }} onClick={() => onToggleEngineer(eng.id)}>
          {off ? 'Bring back on shift' : 'Take off shift (what-if)'}
        </button>
      </div>
      {route?.stops.length ? (
        <ol className="stops">
          {route.stops.map((s, i) => {
            const j = jobs[s.job_id]
            return (
              <li key={s.job_id} onClick={() => onSelect({ type: 'job', id: s.job_id })}>
                <span className="n">{i + 1}</span>
                <span><b>{s.job_id}</b> <span className="muted">{j.tool}</span> <span className={`badge p${j.priority}`}>{PRIORITY[j.priority].label}</span></span>
                <span className="num muted">{clock(s.start)}</span>
              </li>
            )
          })}
        </ol>
      ) : <div className="empty">{off ? 'Off shift, so not considered.' : 'No jobs in this plan.'}</div>}
    </>
  )
}

export default function Inspector({ selection, scenario, results, active, offShift, onToggleEngineer, onSelect }) {
  const result = results.find((r) => r.algorithm === active)
  let body
  if (selection?.type === 'job') {
    const job = scenario.jobs.find((j) => j.id === selection.id)
    if (job) body = <JobView job={job} results={results} active={active} onSelect={onSelect} />
  } else if (selection?.type === 'engineer') {
    const eng = scenario.engineers.find((e) => e.id === selection.id)
    if (eng) body = <EngineerView eng={eng} result={result} scenario={scenario} offShift={offShift} onToggleEngineer={onToggleEngineer} onSelect={onSelect} />
  }
  return (
    <aside className="card inspector" aria-label="Inspector">
      {body ?? (
        <div className="empty">
          <p style={{ margin: '0 0 6px', color: 'var(--ink)', fontWeight: 600 }}>Select a job or engineer</p>
          Click a job to see how each strategy handled it and why. Click an engineer to see their route, or take them off shift.
        </div>
      )}
    </aside>
  )
}
