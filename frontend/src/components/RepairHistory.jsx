import { useEffect, useState } from 'react'
import { similarRepairs } from '../api.js'
import { activeFab } from '../lib/fab.js'

/** Nearest past repairs for a tool-down (exact k-NN over hashed n-grams; Qdrant optional), with a
 *  duration prediction to compare against the planner's standard estimate. `prediction` is null
 *  with a `reason` and `weak_matches` when the symptom has no similar history. */
export default function RepairHistory({ job }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!job?.symptom || job.kind !== 'down') return
    const c = new AbortController()
    setData(null)
    setError(null)
    similarRepairs(activeFab()?.id, job.skill, job.symptom, c.signal).then(setData).catch((e) => { if (e.name !== 'AbortError') setError(e.message) })
    return () => c.abort()
  }, [job?.id, job?.skill, job?.symptom, job?.kind])

  if (!job?.symptom || job.kind !== 'down') return null
  const p = data?.prediction
  const delta = p ? p.minutes - job.duration : 0
  const weak = data?.weak_matches ?? []
  const indexLine = data?.index && `${data.index.size.toLocaleString()} past repairs · ${data.index.mode === 'exact' ? 'exact search' : data.index.mode.replace('-', ' ')} · ${data.index.embedder}`
  return (
    <div className="repair">
      <p className="eyebrow">Repair history</p>
      <p style={{ margin: '0 0 6px', fontSize: 12.5 }}>Symptom: <i>{job.symptom}</i></p>
      {error && <p className="cell-none" style={{ fontSize: 12 }}>{error}</p>}
      {!data && !error && <div className="skeleton" style={{ height: 64 }} />}
      {p && (
        <>
          <div className="pred">
            <strong className="num">{p.minutes} min</strong>
            <span className="muted">predicted (p10–p90 {p.p10}–{p.p90}) vs {job.duration} min planned</span>
            {Math.abs(delta) >= 10 && <span className={`delta ${delta > 0 ? 'bad' : 'good'}`}>{delta > 0 ? '▲' : '▼'} {Math.abs(delta)} min</span>}
          </div>
          <p style={{ margin: '0 0 4px', fontSize: 12.5 }}>Likely cause: <b>{p.likely_cause}</b> <span className="muted">({Math.round(p.cause_share * 100)}% of similar cases)</span></p>
          {data.experienced_engineers?.length > 0 && (
            <p style={{ margin: 0, fontSize: 12.5 }}>Fixed this before: {data.experienced_engineers.slice(0, 3).map(([e, n]) => `${e} (${n}×)`).join(', ')}</p>
          )}
          <ol className="neigh">
            {data.neighbours.slice(0, 4).map((n) => (
              <li key={n.id}><span className="score">{Math.round(n.score * 100)}%</span><span>{n.symptom}: {n.fix}</span><span className="num muted">{n.minutes}m · {n.engineer}</span></li>
            ))}
          </ol>
          {indexLine && <p className="help" style={{ marginTop: 8 }}>{indexLine}</p>}
        </>
      )}
      {data && !p && (
        <>
          {/* Cold start: the nearest records are different faults, so no forecast; show them only as weak matches. */}
          <p className="pred" style={{ fontSize: 12.5 }}>
            <strong>No prediction</strong>
            <span className="muted">{data.reason ?? 'no similar repair history'}; the planner's {job.duration} min estimate stands.</span>
          </p>
          {weak.length > 0 && (
            <>
              <p className="eyebrow" style={{ marginTop: 6 }}>Weak matches <span className="muted" style={{ textTransform: 'none', letterSpacing: 0 }}>· nearest records, below the similarity needed to predict</span></p>
              <ol className="neigh" aria-label="Weak matches">
                {weak.slice(0, 4).map((n) => (
                  <li key={n.id}><span className="score muted">{Math.round(n.score * 100)}% weak</span><span>{n.symptom}: {n.fix}</span><span className="num muted">{n.minutes}m · {n.engineer}</span></li>
                ))}
              </ol>
            </>
          )}
          {indexLine && <p className="help" style={{ marginTop: 8 }}>{indexLine}</p>}
        </>
      )}
    </div>
  )
}
