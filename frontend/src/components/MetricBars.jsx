import { ALGO_ORDER, ALGO_SHORT, METRICS, absentText, bestOf, hasMetric } from '../lib/metrics.js'
import { fmt } from '../lib/format.js'
import { onActivateKey } from '../lib/a11y.js'

/** Small multiples: one short bar chart per metric, one bar per algorithm, values labelled directly. */
export default function MetricBars({ results, keys, onPick, highlight }) {
  const ordered = ALGO_ORDER.map((a) => results.find((r) => r.algorithm === a)).filter(Boolean)
  return (
    <div className="multiples">
      {keys.map((key) => {
        const def = METRICS[key]
        const vals = ordered.map((r) => r.metrics[key]).filter(Number.isFinite)
        const max = Math.max(0, ...vals.map(Math.abs)) || 1
        const best = bestOf(ordered, key)
        const allEqual = vals.every((v) => v === vals[0])
        const shown = (v) => (Number.isFinite(v) ? `${fmt(v)} ${def.unit}`.trim() : absentText(key))
        return (
          <figure key={key} className="mchart" style={{ margin: 0 }}>
            <h3>{def.label}<span>{def.unit} · {def.better === 'max' ? 'higher' : 'lower'} is better</span></h3>
            {def.help && <p className="mnote">{def.help}</p>}
            {ordered.map((r) => {
              const v = r.metrics[key]
              const has = hasMetric(r.metrics, key)
              return (
                <div key={r.algorithm} className="mbar" title={`${r.label}: ${shown(v)}`}
                  {...(onPick ? {
                    role: 'button', tabIndex: 0, onClick: () => onPick(r.algorithm), onKeyDown: onActivateKey(() => onPick(r.algorithm)),
                    'aria-label': `${ALGO_SHORT[r.algorithm]}, ${def.label}: ${shown(v)}. Open on the floor plan`,
                  } : {})}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span className={`swatch ${r.algorithm === highlight ? 'is-reco' : ''}`} />{ALGO_SHORT[r.algorithm]}</span>
                  <span className="track"><span className={`fill ${r.algorithm === highlight ? 'is-reco' : ''}`} style={{ width: `${has ? (Math.abs(v) / max) * 100 : 0}%` }} /></span>
                  <span className={`v ${has && v === best && !allEqual ? 'best' : ''} ${has ? '' : 'muted'}`}>{has ? fmt(v) : absentText(key)}</span>
                </div>
              )
            })}
          </figure>
        )
      })}
    </div>
  )
}
