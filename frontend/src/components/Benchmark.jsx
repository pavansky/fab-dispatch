import { useState } from 'react'
import { optimalityGap, runBenchmark } from '../api.js'
import { bootstrapMeanCI, mean } from '../lib/stats.js'
import { ALGO_ORDER, ALGO_SHORT, METRICS, absentText, workloadKey } from '../lib/metrics.js'
import { fmt, listOf, ms, plural } from '../lib/format.js'
import { speedup } from '../lib/analysis.js'
import { FEW_SEEDS, analyseBenchmark, estimateSeconds } from '../lib/benchmark.js'
import { useTooltip, Tooltip } from './Tooltip.jsx'
import FrontierChart from './FrontierChart.jsx'
import InfoLink from './InfoLink.jsx'

const cellMean = (xs) => { const f = xs.filter(Number.isFinite); return f.length ? mean(f) : NaN }
const cols = (runs) => ['coverage_pct', 'critical_coverage_pct', 'mean_response_min', 'wait_min_total', workloadKey(runs), 'objective', 'runtime_ms']

function Strip({ runs, metric, min, max }) {
  const { tip, show, hide, id: tipId } = useTooltip()
  const x = (v) => `${max === min ? 50 : ((v - min) / (max - min)) * 100}%`
  return (
    <>
      {ALGO_ORDER.map((a) => {
        const rs = runs.filter((r) => r.algorithm === a && Number.isFinite(r.metrics?.[metric]))
        const m = rs.length ? mean(rs.map((r) => r.metrics[metric])) : NaN
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
              {Number.isFinite(m) && <span className="mean" style={{ left: x(m) }} title={`mean ${fmt(m)}`} />}
            </div>
            <span className="v">{fmt(m)}</span>
          </div>
        )
      })}
      <Tooltip tip={tip} id={tipId} />
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

export default function Benchmark({ profile, weights, size, canDispatch, limits }) {
  // The API bounds a benchmark by seeds x jobs (benchmark_max_job_runs, 1,000 on the hosted demo).
  const maxJobRuns = limits?.benchmark_max_job_runs ?? 1000
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
        const out = await runBenchmark({ fab_id: profile.id, preset, seeds, weights, n_engineers: size.n_engineers, n_jobs: Math.min(size.n_jobs, Math.floor(maxJobRuns / seeds)) })
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
  const jobs = Math.min(size.n_jobs, Math.floor(maxJobRuns / seeds))
  const estimate = estimateSeconds(seeds, presets.length, { n_engineers: size.n_engineers, n_jobs: jobs })
  // Verdicts for every preset at once: the Holm adjustment spans the whole run.
  const analysis = data ? analyseBenchmark(data.runs, presets) : null
  const holmNote = analysis && analysis.comparisons > 1 ? `, Holm-adjusted across ${analysis.comparisons} comparisons` : ''
  const COLS = cols(data?.runs ?? [])
  const VERDICT = {
    lowest: <span className="sig">Lowest cost</span>,
    notsig: <span className="tied">Not significantly different (CI ∋ 0)</span>,
    costlier: <span className="tied" style={{ color: 'var(--ink-2)' }}>Significantly costlier</span>,
    nodata: <span className="tied muted">No data (fewer than 2 paired shifts)</span>,
  }
  return (
    <>
      <section className="card">
        <div className="card-h">
          <div><div className="h-row"><h2>Benchmark across many shifts</h2><InfoLink slug="benchmark" label="Benchmark" /></div>
            <p>One scenario can be luck. This runs all five strategies on {seeds} seeded shifts for each of the {presets.length} presets ({size.n_engineers} engineers, {jobs} jobs, current weights). Takes about {estimate} s the first time; cached after.</p></div>
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
        {seeds < FEW_SEEDS && (
          <p className="help warn-note" role="note" style={{ margin: '0 18px 14px' }}>
            With fewer than {FEW_SEEDS} shifts per preset the intervals are approximate: a few shifts can neither show nor rule out a small difference. Pick 10 or 20 seeds for verdicts to rely on.
          </p>
        )}
      </section>

      <GapPanel weights={weights} fabId={profile.id} canDispatch={canDispatch} />

      {analysis && presets.filter((p) => analysis.presets[p]).map((p, pi) => {
        const an = analysis.presets[p]
        const { runs, seedsRun, algos, series, meanCost, latency, best, vsBest, value, notSig, noData } = an
        const vals = runs.map((r) => r.metrics?.[metric]).filter(Number.isFinite)
        const n = `n = ${plural(seedsRun.length, 'shift')}`
        const ciOf = Object.fromEntries(algos.map((a) => [a, bootstrapMeanCI(series(a, 'objective'))]))
        const pts = algos.filter((a) => Number.isFinite(meanCost[a]) && Number.isFinite(latency[a]))
          .map((a) => ({ key: a, cost: meanCost[a], latency: latency[a], costLo: ciOf[a].lo, costHi: ciOf[a].hi, reco: a === value }))
        const front = new Set(pts.filter((q) => !pts.some((o) => o !== q && o.cost <= q.cost && o.latency <= q.latency && (o.cost < q.cost || o.latency < q.latency))).map((q) => q.key))
        pts.forEach((q) => { q.front = front.has(q.key) })
        const ciText = (a) => `${fmt(vsBest[a].lo)} to ${fmt(vsBest[a].hi)} pts`
        return (
          <section key={p} className="card">
            <div className="card-h"><div><h2><span className="section-no">{String(pi + 1).padStart(2, '0')}</span>{meta.presets[p].label}</h2><p>{meta.presets[p].description}</p></div></div>
            <div className="card-b">
              {!best ? (
                <p className="help" style={{ marginTop: 0 }}><b>No verdict:</b> no strategy has a cost for these shifts.</p>
              ) : (
                <p className="help" style={{ marginTop: 0 }}>
                  <b className="sig">Best value: {ALGO_SHORT[value]}.</b>{' '}
                  {value !== best ? (
                    `${ALGO_SHORT[best]} has the lowest mean cost, but ${ALGO_SHORT[value]} is not significantly costlier at ${n} `
                    + `(paired 95% CI of the difference${holmNote}, ${ciText(value)}, includes 0). `
                    + `That is not proof they are equivalent, only that this many shifts can't tell them apart. `
                    + `${ALGO_SHORT[value]} is ${speedup(latency[value], latency[best]) ?? 'about as fast'} (${ms(latency[value])} vs ${ms(latency[best])}).`
                  ) : notSig.length === 0 ? (
                    `It has the lowest mean cost, and every other strategy${noData.length ? ' with data' : ''} is significantly costlier at ${n} (paired 95% CI${holmNote} excludes 0).`
                  ) : (
                    `It has the lowest mean cost and is also the fastest of the strategies not significantly different from it at ${n} `
                    + `(${listOf(notSig.map((a) => ALGO_SHORT[a]))}).`
                  )}
                  {noData.length > 0 && ` No data for ${listOf(noData.map((a) => ALGO_SHORT[a]))}: fewer than 2 shifts where both it and ${ALGO_SHORT[best]} solved.`}
                </p>
              )}
              {an.fewSeeds && <p className="help warn-note" role="note">Only {plural(seedsRun.length, 'shift')}: the intervals are approximate, and a verdict of "not significantly different" means little at this size.</p>}
              <div className="grid-2" style={{ alignItems: 'start' }}>
                <FrontierChart points={pts} caption={`Mean over ${plural(seedsRun.length, 'shift')}. Whiskers: 95% bootstrap CI of each strategy's own mean cost (unpaired). `
                  + 'The verdicts use paired differences over the same shifts, which are tighter, so overlapping whiskers do not by themselves mean a tie. Ringed: best value.'} />
                <div>
                  <p className="eyebrow">{METRICS[metric].label} per shift · bar = mean · {METRICS[metric].better === 'max' ? 'higher' : 'lower'} is better</p>
                  <Strip runs={runs} metric={metric} min={Math.min(...vals)} max={Math.max(...vals)} />
                </div>
              </div>
              <div className="table-wrap" tabIndex={0} style={{ marginTop: 14 }}>
                <table className="data bench-table">
                  <thead><tr><th>Mean of {seedsRun.length}</th>{COLS.map((k) => <th key={k} className="r" title={METRICS[k].label}>{METRICS[k].short ?? METRICS[k].label.split(' ')[0]} <span className="muted">{METRICS[k].unit}</span></th>)}<th className="r">Δ cost vs cheapest · paired 95% CI{holmNote}</th><th>Verdict</th></tr></thead>
                  <tbody>
                    {algos.map((a) => {
                      const ci = vsBest[a]
                      const verdict = an.verdict(a)
                      return (
                        <tr key={a} style={{ cursor: 'default' }}>
                          <td><span className="cell-eng"><span className={`swatch ${a === value ? 'is-reco' : ''}`} />{ALGO_SHORT[a]}</span></td>
                          {COLS.map((k) => { const v = cellMean(series(a, k)); return <td key={k} className="r num">{Number.isFinite(v) ? fmt(v) : <span className="muted">{absentText(k)}</span>}</td> })}
                          <td className="r num">{ci && ci.n >= 2 ? `${ci.mean >= 0 ? '+' : ''}${fmt(ci.mean)} [${fmt(ci.lo)}, ${fmt(ci.hi)}]` : ci && ci.n === 1 ? `${ci.mean >= 0 ? '+' : ''}${fmt(ci.mean)} (1 shift)` : '—'}</td>
                          <td>{VERDICT[verdict]}</td>
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
