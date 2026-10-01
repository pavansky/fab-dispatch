import { FAMILY_COLORS, fmtTime } from '../theme.js'

const SHIFT = 720

export default function Timeline({ scenario, result, selectedJob, onSelectJob }) {
  const jobs = Object.fromEntries(scenario.jobs.map((j) => [j.id, j]))
  const ticks = [0, 120, 240, 360, 480, 600, 720]
  return (
    <div className="timeline">
      <div className="tl-row tl-axis">
        <span className="tl-name" />
        <div className="tl-track">
          {ticks.map((t) => <span key={t} className="tick" style={{ left: `${(t / SHIFT) * 100}%` }}>{fmtTime(t)}</span>)}
        </div>
      </div>
      {result.routes.map((r) => {
        const eng = scenario.engineers.find((e) => e.id === r.tech_id)
        return (
          <div className="tl-row" key={r.tech_id}>
            <span className="tl-name" title={eng?.name}>{r.tech_id} <small>{eng?.name}</small></span>
            <div className="tl-track">
              {r.stops.map((s) => {
                const j = jobs[s.job_id]
                return (
                  <span key={s.job_id}>
                    {s.start > s.arrival + 0.5 && (
                      <span className="tl-wait" title={`waiting ${Math.round(s.start - s.arrival)} min for ${s.job_id}`}
                        style={{ left: `${(s.arrival / SHIFT) * 100}%`, width: `${((s.start - s.arrival) / SHIFT) * 100}%` }} />
                    )}
                    <button
                      className={`tl-job ${selectedJob === s.job_id ? 'sel' : ''} ${j.priority === 3 ? 'crit' : ''}`}
                      style={{ left: `${(s.start / SHIFT) * 100}%`, width: `${((s.end - s.start) / SHIFT) * 100}%`, background: FAMILY_COLORS[j.skill] }}
                      title={`${s.job_id} ${j.tool} ${fmtTime(s.start)}–${fmtTime(s.end)}`}
                      onClick={() => onSelectJob(s.job_id)}
                    >{s.job_id.slice(1)}</button>
                  </span>
                )
              })}
              {!r.stops.length && <span className="tl-idle">no jobs</span>}
            </div>
          </div>
        )
      })}
    </div>
  )
}
