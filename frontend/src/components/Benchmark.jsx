import { useState } from 'react'
import { runBenchmark } from '../api.js'
import { ALGO_ORDER, ALGO_SHORT, METRICS } from '../lib/metrics.js'
import { fmt } from '../lib/format.js'
import { useTooltip, Tooltip } from './Tooltip.jsx'

const COLS = ['coverage_pct', 'critical_coverage_pct', 'mean_response_min', 'wait_min_total', 'workload_std', 'objective', 'runtime_ms']
const mean = (xs) => xs.reduce((a, b) => a + b, 0) / (xs.length || 1)

function Strip({ runs, metric, min, max }) {
  const { tip, show, hide } = useTooltip()
  const x = (v) => `${max === min ? 50 : ((v - min) / (max - min)) * 100}%`
  return (
    <>
      {ALGO_ORDER.map((a) => {
        const rs = runs.filter((r) => r.algorithm === a)
        const m = mean(rs.map((r) => r.metrics[metric]))
        return (
          <div key={a} className="mbar" style={{ gridTemplateColumns: '74px 1fr 52px' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span className={`swatch sw-${a}`} />{ALGO_SHORT[a]}</span>
            <div className="strip">
              <span className="axis" />
              {rs.map((r) => (
                <i key={r.seed} style={{ left: x(r.metrics[metric]), background: `var(--s-${a})` }}
                  onMouseMove={(e) => show(e, <><div className="t">{ALGO_SHORT[a]} · seed {r.seed}</div><div className="r">{fmt(r.metrics[metric])} {METRICS[metric].unit}</div></>)}
                  onMouseLeave={hide} />
              ))}
              <span className="mean" style={{ left: x(m) }} title={`mean ${fmt(m)}`} />
            </div>
            <span className="v">{fmt(m)}</span>
          </div>
        )
      })}
      <Tooltip tip={tip} />
    </>
  )
}

export default function Benchmark({ meta, weights, size }) {
  const [seeds, setSeeds] = useState(20)
  const [metric, setMetric] = useState('objective')
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const run = () => {
    setBusy(true)
    setError(null)
    runBenchmark({ seeds, weights, n_engineers: size.n_engineers, n_jobs: size.n_jobs, presets: Object.keys(meta.presets) })
      .then(setData).catch((e) => setError(e.message)).finally(() => setBusy(false))
  }

  const presets = Object.keys(meta.presets)
  return (
    <>
      <section className="card">
        <div className="card-h">
          <div><h2>Benchmark across many shifts</h2>
            <p>One scenario can be luck. This runs every strategy on {seeds} seeded shifts for each of the {presets.length} presets ({size.n_engineers} engineers, {size.n_jobs} jobs, current weights).</p></div>
        </div>
        <div className="card-b" style={{ display: 'flex', gap: 12, alignItems: 'end', flexWrap: 'wrap' }}>
          <label className="field" style={{ margin: 0, width: 140 }}><span>Seeds per preset</span>
            <select className="input" value={seeds} onChange={(e) => setSeeds(+e.target.value)}>{[5, 10, 20, 30].map((n) => <option key={n}>{n}</option>)}</select>
          </label>
          <label className="field" style={{ margin: 0, width: 240 }}><span>Distribution of</span>
            <select className="input" value={metric} onChange={(e) => setMetric(e.target.value)}>
              {COLS.map((k) => <option key={k} value={k}>{METRICS[k].label}</option>)}
            </select>
          </label>
          <button className="btn primary" onClick={run} disabled={busy}>{busy ? 'Running…' : data ? 'Re-run benchmark' : 'Run benchmark'}</button>
          {error && <span className="error-bar">{error}</span>}
        </div>
      </section>

      {data && presets.map((p) => {
        const runs = data.runs.filter((r) => r.preset === p)
        const vals = runs.map((r) => r.metrics[metric])
        const seedsRun = [...new Set(runs.map((r) => r.seed))]
        const wins = Object.fromEntries(ALGO_ORDER.map((a) => [a, 0]))
        seedsRun.forEach((s) => {
          const rs = runs.filter((r) => r.seed === s)
          const best = Math.min(...rs.map((r) => r.metrics.objective))
          rs.forEach((r) => { if (r.metrics.objective <= best + 1e-6) wins[r.algorithm] += 1 })
        })
        return (
          <section key={p} className="card">
            <div className="card-h"><div><h2>{meta.presets[p].label}</h2><p>{meta.presets[p].description}</p></div></div>
            <div className="card-b grid-2" style={{ alignItems: 'start' }}>
              <div>
                <p className="eyebrow">{METRICS[metric].label} per seed · bar = mean · {METRICS[metric].better === 'max' ? 'higher' : 'lower'} is better</p>
                <Strip runs={runs} metric={metric} min={Math.min(...vals)} max={Math.max(...vals)} />
              </div>
              <div className="table-wrap">
                <table className="data bench-table">
                  <thead><tr><th>Mean of {seedsRun.length}</th>{COLS.map((k) => <th key={k} className="r" title={METRICS[k].label}>{METRICS[k].label.split(' ')[0]} <span className="muted">{METRICS[k].unit}</span></th>)}<th className="r">Lowest cost</th></tr></thead>
                  <tbody>
                    {ALGO_ORDER.map((a) => {
                      const rs = runs.filter((r) => r.algorithm === a)
                      return (
                        <tr key={a} style={{ cursor: 'default' }}>
                          <td><span className="cell-eng"><span className={`swatch sw-${a}`} />{ALGO_SHORT[a]}</span></td>
                          {COLS.map((k) => <td key={k} className="r num">{fmt(mean(rs.map((r) => r.metrics[k])))}</td>)}
                          <td className="r num"><b>{wins[a]}</b>/{seedsRun.length}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        )
      })}
    </>
  )
}
