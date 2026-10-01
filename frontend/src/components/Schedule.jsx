import { PRIORITY, clock, fmt } from '../lib/format.js'
import { shiftLength } from '../lib/fab.js'
import { useTooltip, Tooltip } from './Tooltip.jsx'


export default function Schedule({ scenario, result, selection, onSelect, offShift, now }) {
  const { tip, show, hide } = useTooltip()
  const SHIFT_MIN = shiftLength()
  const pct = (m) => `${(m / SHIFT_MIN) * 100}%`
  const jobs = Object.fromEntries(scenario.jobs.map((j) => [j.id, j]))
  const routes = Object.fromEntries(result.routes.map((r) => [r.tech_id, r]))
  const selJob = selection?.type === 'job' ? jobs[selection.id] : null
  const hours = Array.from({ length: SHIFT_MIN / 60 + 1 }, (_, i) => i * 60)
  const speed = scenario.settings.walk_m_per_min

  return (
    <div className="gantt" role="table" aria-label={`Shift schedule, ${result.label}`}>
      <div className="g-row head" role="row">
        <div className="g-name muted" role="columnheader">Engineer</div>
        <div className="g-head-track" role="columnheader" aria-label="Time">
          {hours.filter((h) => h % (SHIFT_MIN > 600 ? 120 : 60) === 0).map((h) => <span key={h} className="g-tick" style={{ left: pct(h) }}>{clock(h)}</span>)}
        </div>
        <div className="g-util muted" role="columnheader">Busy</div>
      </div>
      {scenario.engineers.map((e) => {
        const r = routes[e.id]
        const off = offShift.has(e.id)
        const busy = r?.stops.reduce((s, x) => s + (x.end - x.start), 0) ?? 0
        return (
          <div key={e.id} className={`g-row ${off ? 'off' : ''}`} role="row" style={!r && !off ? { opacity: 0.6 } : undefined}>
            <div className="g-name" role="rowheader" onClick={() => onSelect({ type: 'engineer', id: e.id })}>{e.id}<small>{e.name}</small></div>
            <div className="g-track" role="cell">
              {hours.map((h) => <span key={h} className="g-grid" style={{ left: pct(h) }} />)}
              {now !== undefined && <span className="g-now" style={{ left: pct(now) }} />}
              {selJob && <span className="g-window" style={{ left: pct(selJob.earliest), width: pct(selJob.latest - selJob.earliest) }} />}
              {r?.stops.map((s, i) => {
                const j = jobs[s.job_id]
                const prevEnd = i === 0 ? e.shift_start : r.stops[i - 1].end
                const walk = s.arrival - prevEnd
                return (
                  <span key={s.job_id}>
                    {walk > 0.5 && <span className="g-walk" style={{ left: pct(prevEnd), width: pct(walk) }} />}
                    {s.start > s.arrival + 0.5 && <span className="g-wait" style={{ left: pct(s.arrival), width: pct(s.start - s.arrival) }} />}
                    <button
                      className={`g-bar p${j.priority} ${selection?.id === s.job_id ? 'sel' : ''} ${s.locked ? 'locked' : ''}`}
                      style={{ left: pct(s.start), width: pct(s.end - s.start) }}
                      onClick={() => onSelect({ type: 'job', id: s.job_id })}
                      onMouseMove={(ev) => show(ev, (
                        <>
                          <div className="t">{s.job_id} · {j.tool}</div>
                          <div className="r">{PRIORITY[j.priority].long}</div>
                          <div className="r">{clock(s.start)}–{clock(s.end)} · window {clock(j.earliest)}–{clock(j.latest)}</div>
                          <div className="r">Walk {fmt(walk, 0)} min ({fmt(walk * speed, 0)} m){s.start > s.arrival + 0.5 ? ` · waits ${fmt(s.start - s.arrival, 0)} min` : ''}</div>
                        </>
                      ))}
                      onMouseLeave={hide}
                      aria-label={`${s.job_id} ${clock(s.start)} to ${clock(s.end)}`}
                    >{s.job_id}</button>
                  </span>
                )
              })}
            </div>
            <div className="g-util num" role="cell">{off ? 'off' : `${Math.round((busy / (e.shift_end - e.shift_start)) * 100)}%`}</div>
          </div>
        )
      })}
      <Tooltip tip={tip} />
    </div>
  )
}
