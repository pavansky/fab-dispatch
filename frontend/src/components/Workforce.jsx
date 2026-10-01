import { workforce } from '../lib/analysis.js'
import { FAMILY_LABEL, fmt } from '../lib/format.js'

const FAMILIES = ['litho', 'etch', 'deposition', 'cmp', 'implant', 'metrology']

export default function Workforce({ scenario, result, offShift, onSelect }) {
  const onShift = { ...scenario, engineers: scenario.engineers.filter((e) => !offShift.has(e.id)) }
  const rows = workforce(onShift, result)
  const maxDemand = Math.max(...rows.map((r) => r.demandHours), 1)
  const loads = Object.fromEntries(result.routes.map((r) => [r.tech_id, r.stops.length]))

  return (
    <>
      <section className="card">
        <div className="card-h"><div><h2>Demand vs certified supply</h2><p>By tool family, engineers on shift only. A family with unserved work and few top-level engineers is a staffing problem, not an algorithm problem.</p></div></div>
        <div className="card-b table-wrap">
          <table className="data">
            <thead>
              <tr><th>Tool family</th><th>Jobs</th><th>Demand</th><th className="r">Bottleneck</th><th>Certified (L1 / L2 / L3)</th><th className="r">Highest level needed</th><th className="r">Served</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const gap = r.jobs - r.served
                const topCount = r.maxLevel ? r.byLevel.slice(r.maxLevel - 1).reduce((a, b) => a + b, 0) : 0
                return (
                  <tr key={r.family} style={{ cursor: 'default' }}>
                    <td><b>{FAMILY_LABEL[r.family]}</b></td>
                    <td className="num">{r.jobs}</td>
                    <td className="num"><span className="inline-bar" style={{ width: `${(r.demandHours / maxDemand) * 90}px` }} />{fmt(r.demandHours)} h</td>
                    <td className="num r">{r.bottleneckJobs}</td>
                    <td className="num">{r.certified} <span className="muted">({r.byLevel.join(' / ')})</span></td>
                    <td className="num r">{r.maxLevel ? `L${r.maxLevel}: ${topCount} engineer${topCount === 1 ? '' : 's'}` : '–'}</td>
                    <td className="num r">{r.served}/{r.jobs} {gap > 0 && <span className="gap-flag">⚠ {gap} unserved</span>}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <div className="card-h"><div><h2>Certification matrix</h2><p>Darker = higher level. Click an engineer to inspect their route.</p></div>
          <div className="legend-row" style={{ padding: 0 }}>
            <span><span className="lvl l1">L1</span></span><span><span className="lvl l2">L2</span></span><span><span className="lvl l3">L3</span></span>
          </div>
        </div>
        <div className="card-b table-wrap">
          <table className="data matrix">
            <thead><tr><th>Engineer</th>{FAMILIES.map((f) => <th key={f} style={{ textAlign: 'center' }}>{FAMILY_LABEL[f]}</th>)}<th className="r">Jobs</th></tr></thead>
            <tbody>
              {scenario.engineers.map((e) => (
                <tr key={e.id} onClick={() => onSelect({ type: 'engineer', id: e.id })} style={offShift.has(e.id) ? { opacity: 0.45 } : undefined}>
                  <td><b>{e.id}</b> {e.name}{offShift.has(e.id) && <span className="badge" style={{ marginLeft: 6 }}>off</span>}</td>
                  {FAMILIES.map((f) => (
                    <td key={f} className="lvlcell">{e.skills[f] ? <span className={`lvl l${e.skills[f]}`}>{e.skills[f]}</span> : <span className="none">·</span>}</td>
                  ))}
                  <td className="num r">{loads[e.id] ?? 0}/{e.max_jobs}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}
