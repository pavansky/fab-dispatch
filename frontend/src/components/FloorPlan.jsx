import { useRef } from 'react'
import { FAMILY_COLORS, engineerColor } from '../theme.js'

const PAD = 12

// Fab aisles run on a grid, so walking paths are drawn as L-shaped Manhattan legs.
function manhattanPath(points, H) {
  if (!points.length) return ''
  let d = `M ${points[0].x} ${H - points[0].y}`
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i]
    d += ` L ${b.x} ${H - a.y} L ${b.x} ${H - b.y}`
  }
  return d
}

export default function FloorPlan({
  scenario, result, areas, compact = false, selectedJob, onSelectJob,
  offShift, onToggleEngineer, onFloorClick, addMode,
}) {
  const svgRef = useRef(null)
  const W = scenario.settings.floor_width
  const H = scenario.settings.floor_height
  const engIndex = Object.fromEntries(scenario.engineers.map((e, i) => [e.id, i]))
  const jobById = Object.fromEntries(scenario.jobs.map((j) => [j.id, j]))
  const assignedTo = {}
  result?.assignments.forEach((a) => { assignedTo[a.job_id] = a.tech_id })

  const handleClick = (evt) => {
    if (!addMode || !onFloorClick) return
    const pt = svgRef.current.createSVGPoint()
    pt.x = evt.clientX
    pt.y = evt.clientY
    const p = pt.matrixTransform(svgRef.current.getScreenCTM().inverse())
    onFloorClick({ x: Math.round(p.x * 10) / 10, y: Math.round((H - p.y) * 10) / 10 })
  }

  return (
    <svg
      ref={svgRef}
      className={`floor ${addMode ? 'adding' : ''}`}
      viewBox={`${-PAD} ${-PAD} ${W + 2 * PAD} ${H + 2 * PAD}`}
      onClick={handleClick}
      role="img"
      aria-label={`Fab floor plan${result ? ` for ${result.label}` : ''}`}
    >
      <rect x={0} y={0} width={W} height={H} className="floor-bg" rx={4} />
      {Object.entries(areas).map(([fam, [x0, y0, x1, y1]]) => (
        <g key={fam}>
          <rect x={x0} y={H - y1} width={x1 - x0} height={y1 - y0} rx={3}
            fill={FAMILY_COLORS[fam]} fillOpacity={0.1} stroke={FAMILY_COLORS[fam]} strokeOpacity={0.45} strokeDasharray="3 2" />
          {!compact && (
            <text x={x0 + 4} y={H - y1 + 10} className="area-label" fill={FAMILY_COLORS[fam]}>{fam.toUpperCase()}</text>
          )}
        </g>
      ))}

      {result?.routes.map((r) => {
        const eng = scenario.engineers[engIndex[r.tech_id]]
        if (!eng || !r.stops.length) return null
        const pts = [eng, ...r.stops.map((s) => jobById[s.job_id])]
        return (
          <path key={r.tech_id} d={manhattanPath(pts, H)} fill="none"
            stroke={engineerColor(engIndex[r.tech_id])} strokeWidth={compact ? 1.4 : 1.8} strokeOpacity={0.85} strokeLinejoin="round" />
        )
      })}

      {scenario.jobs.map((j) => {
        const tech = assignedTo[j.id]
        const served = tech !== undefined
        const r = compact ? 3 + j.priority * 0.6 : 3.5 + j.priority
        const selected = selectedJob === j.id
        return (
          <g key={j.id} className="job" onClick={(e) => { e.stopPropagation(); onSelectJob?.(j.id) }}>
            {j.priority === 3 && <circle cx={j.x} cy={H - j.y} r={r + 2.5} className="critical-ring" />}
            <circle cx={j.x} cy={H - j.y} r={r}
              fill={served ? engineerColor(engIndex[tech]) : 'var(--surface)'}
              stroke={served ? 'var(--surface)' : 'var(--danger)'}
              strokeWidth={served ? 1 : 1.6}
              strokeDasharray={served ? undefined : '2 1.5'} />
            {selected && <circle cx={j.x} cy={H - j.y} r={r + 5} className="selected-ring" />}
            <title>{`${j.id} · ${j.tool} · ${j.skill} L${j.min_level} · P${j.priority}${served ? ` → ${tech}` : ' · UNASSIGNED'}`}</title>
          </g>
        )
      })}

      {scenario.engineers.map((e, i) => {
        const off = offShift?.has(e.id)
        const s = compact ? 9 : 12
        return (
          <g key={e.id} className={`engineer ${off ? 'off' : ''}`}
            onClick={(ev) => { ev.stopPropagation(); onToggleEngineer?.(e.id) }}>
            <rect x={e.x - s / 2} y={H - e.y - s / 2} width={s} height={s} rx={2}
              fill={off ? 'var(--muted-bg)' : engineerColor(i)} stroke="var(--surface)" strokeWidth={1.2} />
            {!compact && (
              <text x={e.x} y={H - e.y + 3} textAnchor="middle" className="eng-label">{e.id.slice(1)}</text>
            )}
            <title>{`${e.id} ${e.name} · ${Object.entries(e.skills).map(([k, v]) => `${k} L${v}`).join(', ')}${off ? ' · OFF SHIFT' : ''}${onToggleEngineer ? ' (click to toggle)' : ''}`}</title>
          </g>
        )
      })}
    </svg>
  )
}
