import { ALGO_SHORT } from '../lib/metrics.js'
import { fmt } from '../lib/format.js'
import { useTooltip, Tooltip } from './Tooltip.jsx'

const M = { l: 56, r: 90, t: 16, b: 38 }

/**
 * Cost (y) against solve latency (x, log scale). Lower-left is better on both. The
 * solid line is the efficient frontier: no strategy on it is beaten on both axes. The
 * shaded band is the noise margin above the cheapest plan; anything inside it is
 * treated as equally cheap, so the fastest point in the band is the best value.
 *
 * points: [{ key, cost, latency, costLo?, costHi?, front, reco }]
 */
export default function FrontierChart({ points, margin, caption, wide = false }) {
  const W = wide ? 960 : 560, H = wide ? 300 : 300
  const { tip, show, hide } = useTooltip()
  if (!points.length) return null
  const lat = points.map((p) => Math.max(p.latency, 0.5))
  const xMin = Math.log10(Math.min(...lat) / 2), xMax = Math.log10(Math.max(...lat) * 2)
  const costs = points.flatMap((p) => [p.costLo ?? p.cost, p.costHi ?? p.cost])
  const cheapest = Math.min(...points.map((p) => p.cost))
  const yPad = (Math.max(...costs) - Math.min(...costs)) * 0.15 || 10
  const yMin = Math.max(0, Math.min(...costs) - yPad), yMax = Math.max(...costs, cheapest + (margin ?? 0)) + yPad
  const x = (v) => M.l + ((Math.log10(Math.max(v, 0.5)) - xMin) / (xMax - xMin)) * (W - M.l - M.r)
  const y = (v) => H - M.b - ((v - yMin) / (yMax - yMin)) * (H - M.t - M.b)

  const xTicks = [1, 10, 100, 1000, 10000].filter((t) => Math.log10(t) >= xMin && Math.log10(t) <= xMax)
  const yTicks = Array.from({ length: 4 }, (_, i) => yMin + ((i + 0.5) * (yMax - yMin)) / 4)
  const front = points.filter((p) => p.front).sort((a, b) => a.latency - b.latency)
  // A point off the frontier is beaten on both cost and speed. Name the strategy that beats
  // it (the cheapest one that's also no slower), so a hollow point never looks unexplained.
  const beatenBy = (p) => points
    .filter((o) => o !== p && o.cost <= p.cost && o.latency <= p.latency && (o.cost < p.cost || o.latency < p.latency))
    .sort((a, b) => a.cost - b.cost)[0]

  return (
    <figure style={{ margin: 0 }}>
      <svg className="frontier" viewBox={`0 0 ${W} ${H}`} role="img"
        aria-label={`Cost versus solve latency for ${points.length} strategies`}>
        {margin > 0 && (
          <rect className="band" x={M.l} width={W - M.l - M.r} y={y(cheapest + margin)} height={Math.max(1, y(cheapest) - y(cheapest + margin))} />
        )}
        {yTicks.map((t) => (
          <g key={t}>
            <line className="gridline" x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} />
            <text x={M.l - 8} y={y(t) + 3} textAnchor="end">{fmt(t, 0)}</text>
          </g>
        ))}
        {xTicks.map((t) => (
          <g key={t}>
            <line className="gridline" y1={M.t} y2={H - M.b} x1={x(t)} x2={x(t)} />
            <text x={x(t)} y={H - M.b + 14} textAnchor="middle">{t >= 1000 ? `${t / 1000}s` : `${t}ms`}</text>
          </g>
        ))}
        <g className="axis"><line x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} /><line x1={M.l} x2={M.l} y1={M.t} y2={H - M.b} /></g>
        <text x={(W + M.l) / 2} y={H - 6} textAnchor="middle">SOLVE LATENCY (LOG) →</text>
        <text transform={`translate(12 ${(H - M.b + M.t) / 2}) rotate(-90)`} textAnchor="middle">← OPERATING COST</text>
        {front.length > 1 && <path className="front-line" d={front.map((p, i) => `${i ? 'L' : 'M'} ${x(p.latency)} ${y(p.cost)}`).join(' ')} />}
        {points.filter((p) => !p.front).map((p) => {
          const by = beatenBy(p)
          return by && <line key={`by-${p.key}`} className="beaten-link" x1={x(p.latency)} y1={y(p.cost)} x2={x(by.latency)} y2={y(by.cost)} />
        })}
        {points.map((p) => (
          <g key={p.key}
            onMouseMove={(e) => show(e, (
              <>
                <div className="t">{ALGO_SHORT[p.key]}{p.reco ? ' · recommended' : ''}</div>
                <div className="r">Cost {fmt(p.cost)} pts{p.costLo !== undefined ? ` (95% CI ${fmt(p.costLo)}–${fmt(p.costHi)})` : ''}</div>
                <div className="r">Latency {fmt(p.latency, p.latency < 10 ? 1 : 0)} ms · {p.front ? 'on the frontier' : `beaten on both by ${ALGO_SHORT[beatenBy(p)?.key] ?? 'another strategy'}`}</div>
              </>
            ))}
            onMouseLeave={hide}>
            {p.costLo !== undefined && <line className="whisker" x1={x(p.latency)} x2={x(p.latency)} y1={y(p.costLo)} y2={y(p.costHi)} />}
            {p.reco && <circle className="ring" cx={x(p.latency)} cy={y(p.cost)} r={11} />}
            <circle className={`pt ${p.front ? 'front' : ''} ${p.reco ? 'is-reco' : ''}`} cx={x(p.latency)} cy={y(p.cost)} r={5} />
            <circle cx={x(p.latency)} cy={y(p.cost)} r={14} fill="transparent" />
            <text className={`lbl ${p.reco ? 'is-reco' : ''}`} x={x(p.latency) + 9} y={y(p.cost) - 8}>{ALGO_SHORT[p.key]}</text>
            {!p.front && beatenBy(p) && (
              <text className="lbl-note" x={x(p.latency) + 9} y={y(p.cost) + 16}>beaten by {ALGO_SHORT[beatenBy(p).key]} on cost and speed</text>
            )}
          </g>
        ))}
      </svg>
      {caption && <figcaption className="help" style={{ marginTop: 6 }}>{caption}</figcaption>}
      <Tooltip tip={tip} />
    </figure>
  )
}
