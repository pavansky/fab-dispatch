import { useState } from 'react'
import { optimalityGap, runBenchmark } from '../api.js'
import { mean } from '../lib/stats.js'
import { ALGO_ORDER, ALGO_SHORT, METRICS } from '../lib/metrics.js'
import { fmt } from '../lib/format.js'
import { useTooltip, Tooltip } from './Tooltip.jsx'
import FrontierChart from './FrontierChart.jsx'
import InfoLink from './InfoLink.jsx'
import { bootstrapMeanCI, pairedBootstrapCI } from '../lib/stats.js'

const COLS = ['coverage_pct', 'critical_coverage_pct', 'mean_response_min', 'wait_min_total', 'workload_std', 'objective', 'runtime_ms']

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
            <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span className="swatch" />{ALGO_SHORT[a]}</span>
            <div className="strip">
              <span className="axis" />
              {rs.map((r) => (
                <i key={r.seed} style={{ left: x(r.metrics[metric]), background: 'var(--mark)' }}
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

function GapPanel({ weights, fabId, canDispatch }) {
  const [gap, setGap] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const run = () => {
    setBusy(true); setError(null)
    optimalityGap({ fab_id: fabId, seeds: 6, n_engineers: 4, n_jobs: 12, weights }).then(setGap).catch((e) => setError(e.message)).finally(() => setBusy(false))
  }
  return (
    <section className="card">
      <div className="card-h">
        <div><div className="h-row"><h2><span className="section-no">00</span>Distance from the proven optimum</h2><InfoLink slug="benchmark" anchor="distance-from-the-proven-optimum" label="Optimality gap" /></div>
          <p>On small shifts (4 engineers, 12 jobs) the exact solver enumerates every feasible route and solves a set-partitioning MILP, so we know the true optimum. Gap = how much worse each strategy's total cost is.</p></div>
        <button className="btn" onClick={run} disabled={busy || !canDispatch} title={canDispatch ? undefined : 'Dispatcher role required'}>{busy ? 'Solving to optimality…' : gap ? 'Re-run' : 'Measure gaps'}</button>
      </div>
      <div className="card-b">
        {error && <div className="error-bar">{error}</div>}
        {gap && (() => {
          const max = Math.max(...Object.values(gap.mean_gap_pct), 1)
          return ALGO_ORDER.map((a) => (
            <div key={a} className="mbar" style={{ gridTemplateColumns: '90px 1fr 70px' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span className="swatch" />{ALGO_SHORT[a]}</span>
              <span className="track"><span className="fill" style={{ width: `${(gap.mean_gap_pct[a] / max) * 100}%` }} /></span>
              <span className="v">{fmt(gap.mean_gap_pct[a])}%</span>
            </div>
          ))
        })()}
        {gap && <p className="help" style={{ marginTop: 10 }}>Mean over {gap.rows.length} shifts. 0% = optimal. {gap.note}</p>}
      </div>
    </section>
  )
}

export default function Benchmark({ profile, weights, size, canDispatch }) {
  const meta = { presets: profile.presets }
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
        const out = await runBenchmark({ fab_id: profile.id, preset, seeds, weights, n_engineers: size.n_engineers, n_jobs: Math.min(size.n_jobs, 120) })
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
          <div><div className="h-row"><h2>Benchmark across many shifts</h2><InfoLink slug="benchmark" label="Benchmark" /></div>
            <p>One scenario can be luck. This runs all five strategies on {seeds} seeded shifts for each of the {presets.length} presets ({size.n_engineers} engineers, {Math.min(size.n_jobs, 120)} jobs, current weights). Takes about {Math.round(seeds * presets.length * 0.8)} s the first time; cached after.</p></div>
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
          <button className="btn primary" onClick={run} disabled={busy || !canDispatch}>{busy ? 'Running…' : data ? 'Re-run benchmark' : 'Run benchmark'}</button>
          {!canDispatch && <span className="help" style={{ margin: 0 }}>Benchmarks are compute-heavy, so they need the dispatcher role.</span>}
          {progress && <span className="solving"><span className="spinner" />{progress}</span>}
          {error && <span className="error-bar">{error}</span>}
        </div>
      </section>

      <GapPanel weights={weights} fabId={profile.id} canDispatch={canDispatch} />

      {data && presets.filter((p) => data.runs.some((r) => r.preset === p)).map((p, pi) => {
        const runs = data.runs.filter((r) => r.preset === p)
        const vals = runs.map((r) => r.metrics[metric])
        const seedsRun = [...new Set(runs.map((r) => r.seed))].sort((a, b) => a - b)
        const algos = ALGO_ORDER.filter((a) => runs.some((r) => r.algorithm === a))
        const series = (a, k) => seedsRun.map((sd) => runs.find((r) => r.algorithm === a && r.seed === sd)?.metrics[k] ?? NaN)
        const meanCost = Object.fromEntries(algos.map((a) => [a, mean(series(a, 'objective'))]))
        const best = algos.reduce((x, y) => (meanCost[y] < meanCost[x] ? y : x))
        // Paired over the same seeds: is this strategy really worse than the best, or just noise?
        const vsBest = Object.fromEntries(algos.map((a) => [a, a === best ? null : pairedBootstrapCI(series(a, 'objective'), series(best, 'objective'))]))
        const tied = (a) => a === best || vsBest[a].lo <= 0
        const latency = Object.fromEntries(algos.map((a) => [a, mean(series(a, 'runtime_ms'))]))
        // Best value: fastest strategy statistically tied with the cheapest.
        const value = algos.filter(tied).reduce((x, y) => (latency[y] < latency[x] ? y : x))
        const ciOf = Object.fromEntries(algos.map((a) => [a, bootstrapMeanCI(series(a, 'objective'))]))
        const pts = algos.map((a) => ({ key: a, cost: meanCost[a], latency: latency[a], costLo: ciOf[a].lo, costHi: ciOf[a].hi, reco: a === value }))
        const front = new Set(pts.filter((q) => !pts.some((o) => o !== q && o.cost <= q.cost && o.latency <= q.latency && (o.cost < q.cost || o.latency < q.latency))).map((q) => q.key))
        pts.forEach((q) => { q.front = front.has(q.key) })
        return (
          <section key={p} className="card">
            <div className="card-h"><div><h2><span className="section-no">{String(pi + 1).padStart(2, '0')}</span>{meta.presets[p].label}</h2><p>{meta.presets[p].description}</p></div></div>
            <div className="card-b">
              <p className="help" style={{ marginTop: 0 }}>
                <b className="sig">Best value: {ALGO_SHORT[value]}.</b>{' '}
                {value === best
                  ? `It has the lowest mean cost, and nothing else is statistically tied with it.`
                  : `${ALGO_SHORT[best]} has the lowest mean cost, but ${ALGO_SHORT[value]}'s gap to it is inside the 95% interval, so it isn't a real difference. ${ALGO_SHORT[value]} gets there ${Math.max(1, Math.round(latency[best] / Math.max(latency[value], 0.1)))}× faster.`}
              </p>
              <div className="grid-2" style={{ alignItems: 'start' }}>
                <FrontierChart points={pts} caption={`Mean over ${seedsRun.length} shifts. Whiskers: 95% bootstrap CI of mean cost. Ringed: best value.`} />
                <div>
                  <p className="eyebrow">{METRICS[metric].label} per shift · bar = mean · {METRICS[metric].better === 'max' ? 'higher' : 'lower'} is better</p>
                  <Strip runs={runs} metric={metric} min={Math.min(...vals)} max={Math.max(...vals)} />
                </div>
              </div>
              <div className="table-wrap" style={{ marginTop: 14 }}>
                <table className="data bench-table">
                  <thead><tr><th>Mean of {seedsRun.length}</th>{COLS.map((k) => <th key={k} className="r" title={METRICS[k].label}>{METRICS[k].label.split(' ')[0]} <span className="muted">{METRICS[k].unit}</span></th>)}<th className="r">Δ cost vs best · 95% CI</th><th>Verdict</th></tr></thead>
                  <tbody>
                    {algos.map((a) => {
                      const ci = vsBest[a]
                      return (
                        <tr key={a} style={{ cursor: 'default' }}>
                          <td><span className="cell-eng"><span className={`swatch ${a === value ? 'is-reco' : ''}`} />{ALGO_SHORT[a]}</span></td>
                          {COLS.map((k) => <td key={k} className="r num">{fmt(mean(series(a, k)))}</td>)}
                          <td className="r num">{ci ? `+${fmt(ci.mean)} [${fmt(ci.lo)}, ${fmt(ci.hi)}]` : '—'}</td>
                          <td>{a === best ? <span className="sig">Lowest cost</span> : tied(a) ? <span className="tied">Tied (CI ∋ 0)</span> : <span className="tied" style={{ color: 'var(--ink-2)' }}>Worse</span>}</td>
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
