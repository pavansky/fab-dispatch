import { ALGO_SHORT } from '../lib/metrics.js'
import { fmt } from '../lib/format.js'
import { useTooltip, Tooltip } from './Tooltip.jsx'

const M = { l: 56, r: 90, t: 16, b: 38 }

// How point o dominates point p, in words that stay true when one axis is equal.
const relationTo = (p, o) => (o.cost === p.cost ? `same cost as ${ALGO_SHORT[o.key]}, but slower`
  : o.latency === p.latency ? `as fast as ${ALGO_SHORT[o.key]}, but costlier`
    : `beaten by ${ALGO_SHORT[o.key]} on cost and speed`)

/**
 * Cost (y) against solve latency (x, log scale). Lower-left is better on both. The
 * solid line is the efficient frontier: no strategy on it is beaten on both axes. The
 * optional shaded band is the noise margin: from `band.from` (the cheapest plan the
 * recommendation considered) up to `band.margin` points above it. It is one-sided, and
 * anything inside it counts as equally cheap.
 *
 * points: [{ key, cost, latency, costLo?, costHi?, front, reco, split?, note? }]
 *   split: how the cost breaks down (tooltip); note: why a recommended point that is off
 *   the frontier was still recommended.
 */
export default function FrontierChart({ points, band, caption, wide = false }) {
  const W = wide ? 960 : 560, H = wide ? 300 : 300
  const { tip, show, hide } = useTooltip()
  if (!points.length) return null
  const lat = points.map((p) => Math.max(p.latency, 0.5))
  const xMin = Math.log10(Math.min(...lat) / 2), xMax = Math.log10(Math.max(...lat) * 2)
  const costs = points.flatMap((p) => [p.costLo ?? p.cost, p.costHi ?? p.cost])
  const bandTop = band?.margin > 0 ? band.from + band.margin : null
  const yPad = (Math.max(...costs) - Math.min(...costs)) * 0.15 || 10
  const yMin = Math.max(0, Math.min(...costs) - yPad), yMax = Math.max(...costs, bandTop ?? -Infinity) + yPad
  const x = (v) => M.l + ((Math.log10(Math.max(v, 0.5)) - xMin) / (xMax - xMin)) * (W - M.l - M.r)
  const y = (v) => H - M.b - ((v - yMin) / (yMax - yMin)) * (H - M.t - M.b)

  const xTicks = [1, 10, 100, 1000, 10000].filter((t) => Math.log10(t) >= xMin && Math.log10(t) <= xMax)
  const yTicks = Array.from({ length: 4 }, (_, i) => yMin + ((i + 0.5) * (yMax - yMin)) / 4)
  const front = points.filter((p) => p.front).sort((a, b) => a.latency - b.latency)
  // A point off the frontier is dominated: no better on either axis, worse on at least one.
  // Name the strategy that dominates it (the cheapest one that's also no slower), so a hollow
  // point never looks unexplained.
  const beatenBy = (p) => points
    .filter((o) => o !== p && o.cost <= p.cost && o.latency <= p.latency && (o.cost < p.cost || o.latency < p.latency))
    .sort((a, b) => a.cost - b.cost)[0]
  const status = (p) => {
    if (p.front) return 'on the frontier'
    const by = beatenBy(p)
    if (p.reco) return p.note ?? 'recommended for the planning goal'
    return by ? relationTo(p, by) : 'off the frontier'
  }

  return (
    <figure style={{ margin: 0 }}>
      <svg className="frontier" viewBox={`0 0 ${W} ${H}`} role="img"
        aria-label={`Cost versus solve latency for ${points.length} strategies. The same data follows as a table.`}>
        {bandTop !== null && (
          <rect className="band" x={M.l} width={W - M.l - M.r} y={y(bandTop)} height={Math.max(1, y(band.from) - y(bandTop))} />
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
        <text transform={`translate(12 ${(H - M.b + M.t) / 2}) rotate(-90)`} textAnchor="middle">← TOTAL COST</text>
        {front.length > 1 && <path className="front-line" d={front.map((p, i) => `${i ? 'L' : 'M'} ${x(p.latency)} ${y(p.cost)}`).join(' ')} />}
        {points.filter((p) => !p.front && !p.reco).map((p) => {
          const by = beatenBy(p)
          return by && <line key={`by-${p.key}`} className="beaten-link" x1={x(p.latency)} y1={y(p.cost)} x2={x(by.latency)} y2={y(by.cost)} />
        })}
        {points.map((p) => (
          <g key={p.key}
            onMouseMove={(e) => show(e, (
              <>
                <div className="t">{ALGO_SHORT[p.key]}{p.reco ? ' · recommended' : ''}</div>
                <div className="r">Total cost {fmt(p.cost)} pts{p.costLo !== undefined ? ` (95% CI ${fmt(p.costLo)}–${fmt(p.costHi)})` : ''}</div>
                {p.split && <div className="r">= {p.split}</div>}
                <div className="r">Latency {fmt(p.latency, p.latency < 10 ? 1 : 0)} ms · {status(p)}</div>
              </>
            ))}
            onMouseLeave={hide}>
            {p.costLo !== undefined && <line className="whisker" x1={x(p.latency)} x2={x(p.latency)} y1={y(p.costLo)} y2={y(p.costHi)} />}
            {p.reco && <circle className="ring" cx={x(p.latency)} cy={y(p.cost)} r={11} />}
            {/* The recommended point is always drawn solid: hollow means "dominated, not chosen". */}
            <circle className={`pt ${p.front || p.reco ? 'front' : ''} ${p.reco ? 'is-reco' : ''}`} cx={x(p.latency)} cy={y(p.cost)} r={5} />
            <circle cx={x(p.latency)} cy={y(p.cost)} r={14} fill="transparent" />
            <text className={`lbl ${p.reco ? 'is-reco' : ''}`} x={x(p.latency) + 9} y={y(p.cost) - 8}>{ALGO_SHORT[p.key]}</text>
            {!p.front && !p.reco && beatenBy(p) && (
              <text className="lbl-note" x={x(p.latency) + 9} y={y(p.cost) + 16}>{relationTo(p, beatenBy(p))}</text>
            )}
          </g>
        ))}
      </svg>
      <table className="sr-only">
        <caption>Total cost and solve time per strategy</caption>
        <thead><tr><th scope="col">Strategy</th><th scope="col">Total cost (pts)</th><th scope="col">Solve time (ms)</th><th scope="col">Cost × latency</th></tr></thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.key}>
              <th scope="row">{ALGO_SHORT[p.key]}{p.reco ? ' (recommended)' : ''}</th>
              <td>{fmt(p.cost)}{p.costLo !== undefined ? `, 95% CI ${fmt(p.costLo)} to ${fmt(p.costHi)}` : ''}</td>
              <td>{fmt(p.latency, p.latency < 10 ? 1 : 0)}</td>
              <td>{status(p)}</td>
            </tr>
          ))}
        </tbody>
        {bandTop !== null && <tfoot><tr><td colSpan={4}>Noise margin: up to {fmt(band.margin, 0)} pts above {fmt(band.from)} pts counts as equally cheap.</td></tr></tfoot>}
      </table>
      {caption && <figcaption className="help" style={{ marginTop: 6 }}>{caption}</figcaption>}
      <Tooltip tip={tip} />
    </figure>
  )
}
