const ROWS = [
  ['coverage_pct', 'Jobs covered', '%', 'max'],
  ['critical_coverage_pct', 'Bottleneck downs covered', '%', 'max'],
  ['priority_weighted_coverage_pct', 'Priority-weighted coverage', '%', 'max'],
  ['mean_response_min', 'Mean response to downs', 'min', 'min'],
  ['walk_m_per_job', 'Walking per job', 'm', 'min'],
  ['wait_min_total', 'Idle wait (all engineers)', 'min', 'min'],
  ['overqualification_levels', 'Over-qualification', 'levels', 'min'],
  ['utilization_pct', 'Engineer utilisation', '%', 'max'],
  ['workload_std', 'Workload spread (std)', 'jobs', 'min'],
  ['objective', 'Total objective cost', 'pts', 'min'],
  ['runtime_ms', 'Runtime', 'ms', 'min'],
]

export default function Comparison({ results, active, onSelect }) {
  if (!results?.length) return null
  return (
    <div className="table-wrap">
      <table className="compare">
        <thead>
          <tr>
            <th>Metric</th>
            {results.map((r) => (
              <th key={r.algorithm} className={r.algorithm === active ? 'active' : ''}>
                <button className="linklike" onClick={() => onSelect(r.algorithm)}>{r.label}</button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map(([key, label, unit, better]) => {
            const vals = results.map((r) => r.metrics[key])
            const best = better === 'max' ? Math.max(...vals) : Math.min(...vals)
            const worst = better === 'max' ? Math.min(...vals) : Math.max(...vals)
            const span = Math.max(...vals.map(Math.abs)) || 1
            return (
              <tr key={key}>
                <th scope="row">{label}<span className="unit"> {unit}</span></th>
                {results.map((r, i) => {
                  const v = vals[i]
                  const isBest = v === best && best !== worst
                  return (
                    <td key={r.algorithm} className={isBest ? 'best' : ''}>
                      <div className="cell">
                        <span className="num">{Number.isInteger(v) ? v : v.toFixed(1)}</span>
                        <span className="bar"><span style={{ width: `${(Math.abs(v) / span) * 100}%` }} /></span>
                      </div>
                    </td>
                  )
                })}
              </tr>
            )
          })}
          <tr>
            <th scope="row">Assigned / total</th>
            {results.map((r) => (
              <td key={r.algorithm}><span className="num">{r.metrics.assigned} / {r.metrics.jobs}</span></td>
            ))}
          </tr>
        </tbody>
      </table>
      <p className="hint">Highlighted cell = best on that metric. The objective is lower-is-better: walking + waiting + over-qualification cost, plus a penalty for every unserved priority point.</p>
    </div>
  )
}
