import { useState } from 'react'
import { ALGO_BLURB, ALGO_ORDER, ALGO_SHORT, METRICS, improvement } from '../lib/metrics.js'
import { GOALS, disagreements, insights, recommend } from '../lib/analysis.js'
import { PRIORITY, fmt } from '../lib/format.js'
import MetricBars from './MetricBars.jsx'

const KPI_KEYS = ['coverage_pct', 'critical_coverage_pct', 'mean_response_min', 'objective']

function Delta({ k, value, base }) {
  if (base === undefined) return <span className="delta flat">baseline</span>
  const gain = improvement(k, value, base)
  if (Math.abs(gain) < 0.05) return <span className="delta flat">= Greedy</span>
  const up = value > base
  return <span className={`delta ${gain > 0 ? 'good' : 'bad'}`}>{up ? '▲' : '▼'} {fmt(Math.abs(value - base))} vs Greedy</span>
}

export default function Overview({ results, scenario, goal, onGoal, onPickAlgo, onSelect }) {
  const [onlyCoverage, setOnlyCoverage] = useState(false)
  const reco = recommend(results, goal)
  const greedy = results.find((r) => r.algorithm === 'greedy')
  const notes = insights(results, scenario)
  const diffs = disagreements(results, scenario.jobs).filter((d) => !onlyCoverage || d.coverageDiffers)
  const jobsTotal = scenario.jobs.length

  return (
    <>
      <section className="card reco" aria-label="Recommendation">
        <div>
          <p className="eyebrow">Recommended dispatch plan</p>
          <h2><span className={`swatch sw-${reco.winner.algorithm}`} style={{ width: 14, height: 14 }} />{reco.winner.label}</h2>
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
          <p className="help" style={{ margin: 0 }}>{GOALS[goal].help}</p>
        </div>
      </section>

      <div className="grid-3">
        {ALGO_ORDER.map((key) => {
          const r = results.find((x) => x.algorithm === key)
          if (!r) return null
          return (
            <section key={key} className={`card score ${reco.winner.algorithm === key ? 'recommended' : ''}`}>
              <div className="score-h">
                <span className={`swatch sw-${key}`} />{r.label}
                {reco.winner.algorithm === key && <span className="badge brand">Recommended</span>}
              </div>
              <p className="help">{ALGO_BLURB[key]}</p>
              <div className="kpis">
                {KPI_KEYS.map((k) => (
                  <div key={k} className="kpi">
                    <div className="label">{METRICS[k].label}</div>
                    <div className="value">{fmt(r.metrics[k])}<small>{METRICS[k].unit}</small></div>
                    {key === 'greedy' ? <span className="delta flat">baseline</span> : <Delta k={k} value={r.metrics[k]} base={greedy?.metrics[k]} />}
                  </div>
                ))}
              </div>
              <button className="btn block" style={{ marginTop: 14 }} onClick={() => onPickAlgo(key)}>View on floor plan</button>
            </section>
          )
        })}
      </div>

      <div className="grid-2">
        <section className="card">
          <div className="card-h"><div><h2>Key findings</h2><p>Generated from this shift's results.</p></div></div>
          <div className="card-b">
            <ul className="insights">
              {notes.map((n, i) => (
                <li key={i}><span className="ico" aria-hidden>{n.icon}</span><span dangerouslySetInnerHTML={{ __html: n.html }} /></li>
              ))}
            </ul>
          </div>
        </section>
        <section className="card">
          <div className="card-h"><div><h2>Where the strategies disagree</h2><p>{diffs.length} of {jobsTotal} jobs. Click a row to inspect it.</p></div>
            <label className="toggle"><input type="checkbox" checked={onlyCoverage} onChange={(e) => setOnlyCoverage(e.target.checked)} />Only served vs unserved</label>
          </div>
          <div className="card-b table-wrap" style={{ maxHeight: 340, overflowY: 'auto' }}>
            {diffs.length === 0 ? <div className="empty">All strategies produce the same assignment.</div> : (
              <table className="data">
                <thead><tr><th>Job</th><th>Type</th>{ALGO_ORDER.map((a) => <th key={a}><span className={`swatch sw-${a}`} /> {ALGO_SHORT[a]}</th>)}</tr></thead>
                <tbody>
                  {diffs.map((d) => (
                    <tr key={d.job.id} onClick={() => onSelect({ type: 'job', id: d.job.id })}>
                      <td><b>{d.job.id}</b> <span className="muted">{d.job.tool}</span></td>
                      <td><span className={`badge p${d.job.priority}`}>{PRIORITY[d.job.priority].label}</span></td>
                      {ALGO_ORDER.map((a) => (
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
        <div className="card-h"><div><h2>Metric comparison</h2><p>Same shift, same constraints, same cost function. Only the decision strategy differs.</p></div></div>
        <div className="card-b">
          <MetricBars results={results} onPick={onPickAlgo}
            keys={['coverage_pct', 'critical_coverage_pct', 'priority_weighted_coverage_pct', 'mean_response_min', 'walk_m_per_job', 'wait_min_total', 'overqualification_levels', 'workload_std', 'utilization_pct', 'objective', 'runtime_ms']} />
        </div>
      </section>
    </>
  )
}
