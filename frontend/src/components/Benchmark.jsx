import { useState } from 'react'
import { optimalityGap, runBenchmark } from '../api.js'
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

function GapPanel({ weights }) {
  const [gap, setGap] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const run = () => {
    setBusy(true); setError(null)
    optimalityGap({ seeds: 6, n_engineers: 4, n_jobs: 12, weights }).then(setGap).catch((e) => setError(e.message)).finally(() => setBusy(false))
  }
  return (
    <section className="card">
      <div className="card-h">
        <div><h2>Distance from the proven optimum</h2>
          <p>On small shifts (4 engineers, 12 jobs) the exact solver enumerates every feasible route and solves a set-partitioning MILP, so we know the true optimum. Gap = how much worse each strategy's total cost is.</p></div>
        <button className="btn" onClick={run} disabled={busy}>{busy ? 'Solving to optimality…' : gap ? 'Re-run' : 'Measure gaps'}</button>
      </div>
      <div className="card-b">
        {error && <div className="error-bar">{error}</div>}
        {gap && (() => {
          const max = Math.max(...Object.values(gap.mean_gap_pct), 1)
          return ALGO_ORDER.map((a) => (
            <div key={a} className="mbar" style={{ gridTemplateColumns: '90px 1fr 70px' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span className={`swatch sw-${a}`} />{ALGO_SHORT[a]}</span>
              <span className="track"><span className="fill" style={{ width: `${(gap.mean_gap_pct[a] / max) * 100}%`, background: `var(--s-${a})` }} /></span>
              <span className="v">{fmt(gap.mean_gap_pct[a])}%</span>
            </div>
          ))
        })()}
        {gap && <p className="help" style={{ marginTop: 10 }}>Mean over {gap.rows.length} shifts. 0% = optimal. {gap.note}</p>}
      </div>
    </section>
  )
}

export default function Benchmark({ meta, weights, size }) {
  const [seeds, setSeeds] = useState(10)
  const [metric, setMetric] = useState('objective')
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(null)
  const [error, setError] = useState(null)

  // One request per preset keeps each call short (serverless-friendly) and lets results
  // appear progressively. Plans are cached server-side, so a re-run is near-instant.
  const run = async () => {
    setBusy(true)
    setError(null)
    const runs = []
    const presets = Object.keys(meta.presets)
    try {
      for (const [i, preset] of presets.entries()) {
        setProgress(`${meta.presets[preset].label} (${i + 1}/${presets.length})`)
        const out = await runBenchmark({ preset, seeds, weights, n_engineers: size.n_engineers, n_jobs: Math.min(size.n_jobs, 120) })
        runs.push(...out.runs)
        setData({ runs: [...runs] })
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
      setProgress(null)
    }
  }

  const presets = Object.keys(meta.presets)
  return (
    <>
      <section className="card">
        <div className="card-h">
          <div><h2>Benchmark across many shifts</h2>
            <p>One scenario can be luck. This runs all five strategies on {seeds} seeded shifts for each of the {presets.length} presets ({size.n_engineers} engineers, {Math.min(size.n_jobs, 120)} jobs, current weights). Takes about {Math.round(seeds * presets.length * 2.2)} s the first time; cached after.</p></div>
        </div>
        <div className="card-b" style={{ display: 'flex', gap: 12, alignItems: 'end', flexWrap: 'wrap' }}>
          <label className="field" style={{ margin: 0, width: 140 }}><span>Seeds per preset</span>
            <select className="input" value={seeds} onChange={(e) => setSeeds(+e.target.value)}>{[5, 10, 20].map((n) => <option key={n}>{n}</option>)}</select>
          </label>
          <label className="field" style={{ margin: 0, width: 240 }}><span>Distribution of</span>
            <select className="input" value={metric} onChange={(e) => setMetric(e.target.value)}>
              {COLS.map((k) => <option key={k} value={k}>{METRICS[k].label}</option>)}
            </select>
          </label>
          <button className="btn primary" onClick={run} disabled={busy}>{busy ? 'Running…' : data ? 'Re-run benchmark' : 'Run benchmark'}</button>
          {progress && <span className="solving"><span className="spinner" />{progress}</span>}
          {error && <span className="error-bar">{error}</span>}
        </div>
      </section>

      <GapPanel weights={weights} />

      {data && presets.filter((p) => data.runs.some((r) => r.preset === p)).map((p) => {
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
