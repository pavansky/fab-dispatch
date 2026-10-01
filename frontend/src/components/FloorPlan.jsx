import { useMemo, useRef, useState } from 'react'
import { FAMILY_LABEL, PRIORITY, clock } from '../lib/format.js'
import { useTooltip, Tooltip } from './Tooltip.jsx'

const PAD = 10

// Bays sit on a grid of aisles, so a walk is drawn as horizontal-then-vertical legs.
function aislePath(points, H) {
  let d = `M ${points[0].x} ${H - points[0].y}`
  for (let i = 1; i < points.length; i++) {
    d += ` H ${points[i].x} V ${H - points[i].y}`
  }
  return d
}

function JobMark({ job, H }) {
  const cx = job.x, cy = H - job.y
  if (job.kind === 'pm') return <rect className="mark" x={cx - 3.2} y={cy - 3.2} width={6.4} height={6.4} rx={1.2} />
  return <circle className="mark" cx={cx} cy={cy} r={job.priority === 3 ? 4.4 : 3.6} />
}

export default function FloorPlan({
  scenario, result, baseline, areas, selection, onSelect, offShift, onToggleEngineer,
  addMode, onFloorClick, showChanges, compact = false,
}) {
  const svgRef = useRef(null)
  const { tip, show, hide } = useTooltip()
  const [hover, setHover] = useState(null)
  const W = scenario.settings.floor_width
  const H = scenario.settings.floor_height

  const engById = useMemo(() => Object.fromEntries(scenario.engineers.map((e) => [e.id, e])), [scenario])
  const jobById = useMemo(() => Object.fromEntries(scenario.jobs.map((j) => [j.id, j])), [scenario])
  const owner = useMemo(() => Object.fromEntries((result?.assignments ?? []).map((a) => [a.job_id, a])), [result])
  const baseOwner = useMemo(() => Object.fromEntries((baseline?.assignments ?? []).map((a) => [a.job_id, a.tech_id])), [baseline])
  const jobsPerArea = useMemo(() => {
    const c = {}
    scenario.jobs.forEach((j) => { c[j.skill] = (c[j.skill] || 0) + 1 })
    return c
  }, [scenario])

  // The engineer whose route is in focus: selected engineer, or owner of the selected/hovered job.
  const focusEng = (() => {
    const pick = hover ?? selection
    if (!pick) return null
    if (pick.type === 'engineer') return pick.id
    return owner[pick.id]?.tech_id ?? null
  })()
  const routeOf = (id) => result?.routes.find((r) => r.tech_id === id)
  const focusStops = focusEng ? routeOf(focusEng)?.stops.map((s) => s.job_id) ?? [] : []

  const handleClick = (evt) => {
    if (!addMode || !onFloorClick) return
    const pt = svgRef.current.createSVGPoint()
    pt.x = evt.clientX
    pt.y = evt.clientY
    const p = pt.matrixTransform(svgRef.current.getScreenCTM().inverse())
    onFloorClick({ x: Math.round(p.x * 10) / 10, y: Math.round((H - p.y) * 10) / 10 })
  }

  const jobTip = (j) => {
    const a = owner[j.id]
    return (
      <>
        <div className="t">{j.id} · {j.tool}</div>
        <div className="r">{PRIORITY[j.priority].long} · {FAMILY_LABEL[j.skill]} L{j.min_level}+</div>
        <div className="r">Start window {clock(j.earliest)}–{clock(j.latest)} · {j.duration} min</div>
        <div className="r" style={{ marginTop: 4 }}>
          {a ? <>→ <b>{a.tech_id}</b> {engById[a.tech_id]?.name}, starts {clock(a.start)}</> : <b style={{ color: 'var(--critical)' }}>Unassigned</b>}
        </div>
      </>
    )
  }
  const engTip = (e) => {
    const r = routeOf(e.id)
    const off = offShift?.has(e.id)
    return (
      <>
        <div className="t">{e.id} · {e.name}</div>
        <div className="r">{Object.entries(e.skills).map(([k, v]) => `${FAMILY_LABEL[k]} L${v}`).join(' · ')}</div>
        <div className="r" style={{ marginTop: 4 }}>{off ? 'Off shift' : `${r?.stops.length ?? 0} of ${e.max_jobs} jobs`}{onToggleEngineer ? ' · click to inspect' : ''}</div>
      </>
    )
  }

  return (
    <>
      <svg
        ref={svgRef}
        className={`floor ${addMode ? 'adding' : ''}`}
        viewBox={`${-PAD} ${-PAD} ${W + 2 * PAD} ${H + 2 * PAD}`}
        onClick={handleClick}
        role="img"
        aria-label={`Fab floor plan${result ? `, ${result.label}` : ''}`}
      >
        <rect className="f-bg" x={0} y={0} width={W} height={H} rx={3} />
        {!compact && Array.from({ length: Math.floor(W / 20) - 1 }, (_, i) => (
          <line key={`gx${i}`} className="f-grid" x1={(i + 1) * 20} x2={(i + 1) * 20} y1={0} y2={H} />
        ))}
        {!compact && Array.from({ length: Math.floor(H / 20) - 1 }, (_, i) => (
          <line key={`gy${i}`} className="f-grid" y1={(i + 1) * 20} y2={(i + 1) * 20} x1={0} x2={W} />
        ))}

        {Object.entries(areas).map(([fam, [x0, y0, x1, y1]]) => (
          <g key={fam}>
            <rect className="f-area" x={x0} y={H - y1} width={x1 - x0} height={y1 - y0} rx={2} />
            <text className="f-area-label" x={x0 + 5} y={H - y1 + 10}>{FAMILY_LABEL[fam].toUpperCase()}</text>
            {!compact && <text className="f-area-sub" x={x0 + 5} y={H - y1 + 17}>{jobsPerArea[fam] ?? 0} jobs</text>}
          </g>
        ))}

        {result?.routes.map((r) => {
          const e = engById[r.tech_id]
          if (!e || !r.stops.length) return null
          const cls = focusEng ? (focusEng === r.tech_id ? 'hi' : 'dim') : ''
          return <path key={r.tech_id} className={`f-route ${cls}`} d={aislePath([e, ...r.stops.map((s) => jobById[s.job_id])], H)} />
        })}

        {scenario.jobs.map((j) => {
          const a = owner[j.id]
          // Only flag coverage changes; who does a job shuffles constantly and would drown the signal.
          const changed = showChanges && baseline && Boolean(baseOwner[j.id]) !== Boolean(a)
          const selected = selection?.type === 'job' && selection.id === j.id
          const dim = focusEng && !focusStops.includes(j.id) && !selected
          const cls = ['f-job', `p${j.priority}`, a ? '' : 'un', changed ? 'changed' : '', selected ? 'sel' : '', dim ? 'dim' : ''].join(' ')
          return (
            <g key={j.id} className={cls}
              onClick={(e) => { e.stopPropagation(); onSelect?.({ type: 'job', id: j.id }) }}
              onMouseMove={(e) => { show(e, jobTip(j)); setHover({ type: 'job', id: j.id }) }}
              onMouseLeave={() => { hide(); setHover(null) }}>
              <circle cx={j.x} cy={H - j.y} r={9} fill="transparent" />
              {(changed || selected) && <circle className="halo" cx={j.x} cy={H - j.y} r={7.2} />}
              <JobMark job={j} H={H} />
              {!a && <path className="x" d={`M ${j.x - 1.6} ${H - j.y - 1.6} l 3.2 3.2 m 0 -3.2 l -3.2 3.2`} />}
            </g>
          )
        })}

        {focusEng && focusStops.map((jid, i) => {
          const j = jobById[jid]
          return <text key={jid} className="f-seq" x={j.x + 5} y={H - j.y - 5}>{i + 1}</text>
        })}

        {scenario.engineers.map((e) => {
          const off = offShift?.has(e.id)
          const sel = selection?.type === 'engineer' && selection.id === e.id
          const dim = focusEng && focusEng !== e.id
          return (
            <g key={e.id} className={`f-eng ${off ? 'off' : ''} ${sel ? 'sel' : ''} ${dim ? 'dim' : ''}`}
              onClick={(ev) => { ev.stopPropagation(); onSelect?.({ type: 'engineer', id: e.id }) }}
              onMouseMove={(ev) => { show(ev, engTip(e)); setHover({ type: 'engineer', id: e.id }) }}
              onMouseLeave={() => { hide(); setHover(null) }}>
              <rect x={e.x - 5.5} y={H - e.y - 5.5} width={11} height={11} rx={2.2} />
              <text x={e.x} y={H - e.y + 1.9} textAnchor="middle">{e.id.slice(1)}</text>
            </g>
          )
        })}
      </svg>
      <Tooltip tip={tip} />
    </>
  )
}
