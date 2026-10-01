import { ALGO_ORDER, ALGO_SHORT, METRICS, bestOf } from '../lib/metrics.js'
import { fmt } from '../lib/format.js'

/** Small multiples: one short bar chart per metric, one bar per algorithm, values labelled directly. */
export default function MetricBars({ results, keys, onPick }) {
  const ordered = ALGO_ORDER.map((a) => results.find((r) => r.algorithm === a)).filter(Boolean)
  return (
    <div className="multiples">
      {keys.map((key) => {
        const def = METRICS[key]
        const vals = ordered.map((r) => r.metrics[key])
        const max = Math.max(...vals.map(Math.abs)) || 1
        const best = bestOf(ordered, key)
        const allEqual = vals.every((v) => v === vals[0])
        return (
          <figure key={key} className="mchart" style={{ margin: 0 }}>
            <h3>{def.label}<span>{def.unit} · {def.better === 'max' ? 'higher' : 'lower'} is better</span></h3>
            {ordered.map((r) => {
              const v = r.metrics[key]
              return (
                <div key={r.algorithm} className="mbar" onClick={() => onPick?.(r.algorithm)} role="button" tabIndex={0}
                  title={`${r.label}: ${fmt(v)} ${def.unit}`}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span className={`swatch sw-${r.algorithm}`} />{ALGO_SHORT[r.algorithm]}</span>
                  <span className="track"><span className="fill" style={{ width: `${(Math.abs(v) / max) * 100}%`, background: `var(--s-${r.algorithm})` }} /></span>
                  <span className={`v ${v === best && !allEqual ? 'best' : ''}`}>{fmt(v)}</span>
                </div>
              )
            })}
          </figure>
        )
      })}
    </div>
  )
}
