import { PRIORITY_LABEL, fmtTime } from '../theme.js'

const REASONS = {
  skill_missing: 'not certified',
  level_too_low: 'level too low',
  at_capacity: 'at max jobs',
  window_missed: "can't reach in window",
  shift_overrun: 'past shift end',
}

export default function JobDetail({ job, results, active }) {
  if (!job) return <p className="hint">Click a job on the floor plan or timeline to see why it was assigned (or not).</p>
  return (
    <div className="detail">
      <div className="detail-head">
        <strong>{job.id}</strong> · {job.tool} · <span className={`pill p${job.priority}`}>{PRIORITY_LABEL[job.priority]}</span>
        <div className="sub">
          {job.skill} level {job.min_level}+ · start {fmtTime(job.earliest)}–{fmtTime(job.latest)} · {job.duration} min
        </div>
      </div>
      {results.map((r) => {
        const a = r.assignments.find((x) => x.job_id === job.id)
        const u = r.unassigned.find((x) => x.job_id === job.id)
        return (
          <div key={r.algorithm} className={`decision ${r.algorithm === active ? 'active' : ''}`}>
            <div className="decision-title">
              {r.label}: {a ? <b>{a.tech_id}</b> : <b className="danger">unassigned</b>}
              {a && <span className="sub"> · stop #{a.sequence}, starts {fmtTime(a.start)}</span>}
            </div>
            {a && (
              <>
                <p>{a.explanation}</p>
                <div className="breakdown">
                  {Object.entries(a.cost_breakdown).map(([k, v]) => (
                    <span key={k} className={v < 0 ? 'neg' : ''}>{k} {v > 0 ? '+' : ''}{v.toFixed(1)}</span>
                  ))}
                </div>
              </>
            )}
            {u && (
              <>
                <p>{u.reason}</p>
                <div className="breakdown">
                  {Object.entries(u.rejections).map(([k, v]) => <span key={k}>{v}× {REASONS[k] ?? k}</span>)}
                </div>
              </>
            )}
          </div>
        )
      })}
    </div>
  )
}
