import { useEffect, useState } from 'react'
import { ALGO_BLURB, ALGO_KIND, ALGO_ORDER, ALGO_SHORT, METRICS, improvement, presentKeys } from '../lib/metrics.js'
import { GOALS, costSplitText, disagreements, insights, paretoFront } from '../lib/analysis.js'
import FrontierChart from './FrontierChart.jsx'
import { PRIORITY, fmt } from '../lib/format.js'
import MetricBars from './MetricBars.jsx'
import InfoLink from './InfoLink.jsx'

const KPI_KEYS = ['coverage_pct', 'critical_coverage_pct', 'mean_response_min', 'objective']
const BAR_KEYS = ['coverage_pct', 'critical_coverage_pct', 'priority_weighted_coverage_pct', 'mean_response_min', 'walk_m_per_job', 'wait_min_total', 'overqualification_levels', 'workload_std', 'utilization_pct', 'objective']

function Delta({ k, value, base }) {
  if (base === undefined) return <span className="delta flat">baseline</span>
  const gain = improvement(k, value, base)
  if (Math.abs(gain) < 0.05) return <span className="delta flat">= Greedy</span>
  const up = value > base
  return <span className={`delta ${gain > 0 ? 'good' : 'bad'}`}>{up ? '▲' : '▼'} {fmt(Math.abs(value - base))} vs Greedy</span>
}

function useWide(min = 760) {
  const query = `(min-width: ${min}px)`
  const [wide, setWide] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const m = window.matchMedia(query)
    const on = () => setWide(m.matches)
    m.addEventListener('change', on)
    return () => m.removeEventListener('change', on)
  }, [query])
  return wide
}

/** A finding's text: plain strings, with { b } parts emphasised. Never parsed as HTML. */
function FindingText({ parts }) {
  return <span>{parts.map((p, i) => (typeof p === 'string' ? p : <b key={i}>{p.b}</b>))}</span>
}

export default function Overview({ results, pending, reco, scenario, weights, goal, onGoal, onPickAlgo, onSelect }) {
  const wide = useWide()
  const [onlyCoverage, setOnlyCoverage] = useState(false)
  const greedy = results.find((r) => r.algorithm === 'greedy')
  // Findings compare strategies, so they wait for the full field rather than mislead early.
  const notes = reco.provisional ? null : insights(results, scenario, { weights })
  const solved = ALGO_ORDER.filter((a) => results.some((r) => r.algorithm === a))
  const diffs = disagreements(results, scenario.jobs).filter((d) => !onlyCoverage || d.coverageDiffers)
  const jobsTotal = scenario.jobs.length

  return (
    <>
      <section className="card reco" aria-label="Recommendation" data-tour="reco">
        <div>
          <p className="eyebrow"><span className="sig">{reco.provisional ? '◌ Provisional' : '● Recommended'}</span> dispatch plan{pending.size > 0 && <span className="solving" style={{ marginLeft: 8, textTransform: 'none', letterSpacing: 0 }}><span className="spinner" />waiting for {[...pending].map((a) => ALGO_SHORT[a]).join(', ')}</span>}</p>
          <h2>{reco.winner.label}</h2>
          <p>{reco.why}</p>
          {reco.tradeoff.length > 0 && <p className="tradeoff">Trade-off: {reco.tradeoff.join('; ')}.</p>}
        </div>
        <div style={{ minWidth: 240 }}>
          <label className="field">
            <span>Planning goal</span>
            <select className="input" value={goal} onChange={(e) => onGoal(e.target.value)}>
              {Object.entries(GOALS).map(([k, g]) => <option key={k} value={k}>{g.label}</option>)}
            </select>
          </label>
          <p className="help" style={{ margin: 0 }}>{GOALS[goal].help} <InfoLink slug="recommendation" anchor="planning-goals" label="Planning goals" /></p>
        </div>
      </section>

      <section className="card" data-tour="frontier">
        <div className="card-h"><div><div className="h-row"><h2><span className="section-no">01</span>Cost × latency</h2><InfoLink slug="recommendation" anchor="the-cost-latency-chart" label="Cost × latency chart" /></div>
          <p>Lower-left is better on both. The line is the efficient frontier: nothing on it is beaten on both cost and speed. A hollow point is beaten on both, and its dashed line points to the strategy that beats it. The shaded band is the noise margin ({reco.margin ? `±${fmt(reco.margin, 0)} pts` : 'per goal'}) above the cheapest plan; differences inside it aren't counted as wins.</p></div></div>
        <div className="card-b">
          <FrontierChart wide={wide} margin={goal === 'value' ? reco.margin : 0}
            points={(() => {
              const front = new Set(paretoFront(results).map((r) => r.algorithm))
              return results.map((r) => ({ key: r.algorithm, cost: r.metrics.objective, latency: r.metrics.runtime_ms,
                front: front.has(r.algorithm), reco: r.algorithm === reco.winner.algorithm }))
            })()} />
        </div>
      </section>

      <div className="cards algos">
        {ALGO_ORDER.map((key) => {
          const r = results.find((x) => x.algorithm === key)
          if (!r) return <div key={key} className="card score skeleton" style={{ minHeight: 260 }} aria-label={`${ALGO_SHORT[key]} solving`} />
          return (
            <section key={key} className={`card score ${reco.winner.algorithm === key ? 'recommended' : ''}`}>
              <div className="score-h">
                <span className={`swatch ${reco.winner.algorithm === key ? 'is-reco' : ''}`} style={{ marginTop: 6 }} />{ALGO_SHORT[key]}
                {reco.winner.algorithm === key && <span className="badge brand">{reco.provisional ? 'Best so far' : 'Recommended'}</span>}
              </div>
              <p className="help"><span className="badge" style={{ marginRight: 6 }}>{ALGO_KIND[key]}</span>{ALGO_BLURB[key]}</p>
              <div className="kpis">
                {KPI_KEYS.map((k) => (
                  <div key={k} className="kpi">
                    <div className="label" title={METRICS[k].label}>{METRICS[k].short ?? METRICS[k].label}</div>
                    <div className="value">{fmt(r.metrics[k])}<small>{METRICS[k].unit}</small></div>
                    {key === 'greedy' ? <span className="delta flat">baseline</span> : <Delta k={k} value={r.metrics[k]} base={greedy?.metrics[k]} />}
                  </div>
                ))}
              </div>
              {costSplitText(r.metrics) && <p className="help num" style={{ margin: 0 }}>Cost = {costSplitText(r.metrics)} pts</p>}
              <button className="btn block" style={{ marginTop: 14 }} onClick={() => onPickAlgo(key)}>View on floor plan</button>
            </section>
          )
        })}
      </div>

      <div className="grid-2">
        <section className="card">
          <div className="card-h"><div><h2><span className="section-no">02</span>Key findings</h2><p>Generated from this shift's results.</p></div></div>
          <div className="card-b">
            {notes ? (
              <ul className="insights">
                {notes.map((n, i) => (
                  <li key={i}><span className="ico" aria-hidden>{n.icon}</span><FindingText parts={n.parts} /></li>
                ))}
              </ul>
            ) : <p className="solving" style={{ margin: 0 }}><span className="spinner" />Findings appear once every strategy has solved.</p>}
          </div>
        </section>
        <section className="card">
          <div className="card-h"><div><h2><span className="section-no">03</span>Where the strategies disagree</h2><p>{diffs.length} of {jobsTotal} jobs. Click a row to inspect it.</p></div>
            <label className="toggle"><input type="checkbox" checked={onlyCoverage} onChange={(e) => setOnlyCoverage(e.target.checked)} />Only served vs unserved</label>
          </div>
          <div className="card-b table-wrap" tabIndex={0} style={{ maxHeight: 340, overflowY: 'auto' }}>
            {diffs.length === 0 ? <div className="empty">All strategies produce the same assignment.</div> : (
              <table className="data">
                <thead><tr><th>Job</th><th>Type</th>{solved.map((a) => <th key={a}>{ALGO_SHORT[a]}</th>)}</tr></thead>
                <tbody>
                  {diffs.map((d) => (
                    <tr key={d.job.id} onClick={() => onSelect({ type: 'job', id: d.job.id })}>
                      <td><b>{d.job.id}</b> <span className="muted">{d.job.tool}</span></td>
                      <td><span className={`badge p${d.job.priority}`}>{PRIORITY[d.job.priority].label}</span></td>
                      {solved.map((a) => (
                        <td key={a}>{d.who[a] ? <span className="cell-eng">{d.who[a]}</span> : <span className="cell-none">—</span>}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>
      </div>

      <section className="card">
        <div className="card-h"><div><h2><span className="section-no">04</span>Metric comparison</h2><p>Same shift, same constraints, same cost function. Only the decision strategy differs.</p></div></div>
        <div className="card-b">
          <MetricBars results={results} onPick={onPickAlgo} highlight={reco.winner.algorithm}
            keys={[...BAR_KEYS, ...presentKeys(results, ['operating_cost', 'workload_cost']), 'runtime_ms']} />
        </div>
      </section>
    </>
  )
}
