import { useCallback, useEffect, useRef, useState } from 'react'
import { advanceShift, createShift, engineerOff, getShift, reportJob, streamUrl } from '../api.js'
import { ALGO_ORDER, ALGO_SHORT } from '../lib/metrics.js'
import { PRIORITY, clock, fmt } from '../lib/format.js'
import FloorPlan from './FloorPlan.jsx'
import Schedule from './Schedule.jsx'

const SPEEDS = [[5, '5 min/s'], [15, '15 min/s'], [30, '30 min/s']]
const SLA = { 3: 45, 2: 120, 1: 240 }

const familyAt = (areas, { x, y }) =>
  Object.entries(areas).find(([, [x0, y0, x1, y1]]) => x >= x0 && x <= x1 && y >= y0 && y <= y1)?.[0]

/**
 * Live dispatch. The shift lives on the server; this view drives the clock and listens
 * on Server-Sent Events, so every open dashboard (another tab, another device) sees each
 * re-plan as it happens. Share the URL to join the same shift.
 */
export default function LiveShift({ scenario, weights, areas, onError }) {
  const [algorithm, setAlgorithm] = useState('alns')
  const [shiftId, setShiftId] = useState(() => new URLSearchParams(location.search).get('shift'))
  const [view, setView] = useState(null)
  const [feed, setFeed] = useState([])
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(15)
  const [busy, setBusy] = useState(false)
  const [connected, setConnected] = useState(false)
  const [selection, setSelection] = useState(null)
  const [reportMode, setReportMode] = useState(false)
  const etag = useRef(null)

  const refresh = useCallback(async (id) => {
    const r = await getShift(id, etag.current)
    if (r.notModified) return
    etag.current = r.etag
    setView(r.data)
  }, [])

  // Join a shift from the URL, or after starting one.
  useEffect(() => {
    if (!shiftId) return
    const url = new URL(location.href)
    url.searchParams.set('shift', shiftId)
    history.replaceState(null, '', url)
    refresh(shiftId).catch((e) => { onError(e.message); setShiftId(null) })
  }, [shiftId, refresh, onError])

  // Realtime: the SSE stream relays the shift's event log; each event triggers a cheap
  // conditional refetch (ETag, so unchanged state costs a 304).
  useEffect(() => {
    if (!shiftId) return
    const es = new EventSource(streamUrl(shiftId))
    const onEvent = (e) => {
      const ev = JSON.parse(e.data)
      setFeed((prev) => (prev.some((x) => x.id === ev.id) ? prev : [ev, ...prev].slice(0, 200)))
      refresh(shiftId).catch(() => {})
    }
    ;['shift_started', 'job_reported', 'replanned', 'engineer_off', 'clock', 'shift_ended'].forEach((k) => es.addEventListener(k, onEvent))
    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false) // EventSource reconnects by itself (Last-Event-ID)
    return () => es.close()
  }, [shiftId, refresh])

  const act = useCallback(async (fn) => {
    setBusy(true)
    try {
      const out = await fn()
      if (out?.state) { setView(out); etag.current = null }
    } catch (e) {
      onError(e.message)
      setPlaying(false)
    } finally {
      setBusy(false)
    }
  }, [onError])

  // Autoplay: one request per second. The server owns the clock, so a closed tab just pauses.
  useEffect(() => {
    if (!playing || !shiftId || view?.state.ended) return
    const t = setInterval(() => { if (!busy) act(() => advanceShift(shiftId, speed)) }, 1000)
    return () => clearInterval(t)
  }, [playing, shiftId, speed, busy, view?.state.ended, act])
  useEffect(() => { if (view?.state.ended) setPlaying(false) }, [view?.state.ended])

  const start = () => act(async () => {
    const out = await createShift(scenario, weights, algorithm)
    setFeed([])
    etag.current = null
    setShiftId(out.state.id)
    return out
  })

  const leave = () => {
    setShiftId(null); setView(null); setFeed([]); setPlaying(false)
    const url = new URL(location.href); url.searchParams.delete('shift'); history.replaceState(null, '', url)
  }

  if (!shiftId || !view) {
    return (
      <section className="card">
        <div className="card-h"><div><h2>Live dispatch</h2>
          <p>Run the current shift in real time. Tool-downs are revealed when they happen (no peeking ahead), started work is locked, and the chosen strategy re-plans open work on every event. Changes stream to every open dashboard.</p></div></div>
        <div className="card-b" style={{ display: 'flex', gap: 12, alignItems: 'end', flexWrap: 'wrap' }}>
          <label className="field" style={{ margin: 0, width: 260 }}><span>Re-dispatch strategy</span>
            <select className="input" value={algorithm} onChange={(e) => setAlgorithm(e.target.value)}>
              {ALGO_ORDER.map((a) => <option key={a} value={a}>{ALGO_SHORT[a]}</option>)}
            </select>
          </label>
          <button className="btn primary" onClick={start} disabled={busy}>{busy ? 'Starting…' : 'Start live shift'}</button>
          <span className="help" style={{ margin: 0 }}>{scenario.engineers.length} engineers · {scenario.jobs.length} jobs over the shift</span>
        </div>
      </section>
    )
  }

  const { state, status, progress } = view
  const plan = state.plan
  const knownJobs = new Set(state.released)
  const visible = { ...state.scenario, jobs: state.scenario.jobs.filter((j) => knownJobs.has(j.id)) }
  const offShift = new Set(Object.keys(state.off_shift))
  const pct = (state.clock / 720) * 100
  const critOpen = state.scenario.jobs.filter((j) => knownJobs.has(j.id) && j.priority === 3 && status[j.id] === 'unassigned').length

  const onFloor = (pt) => {
    if (!reportMode) return
    const fam = familyAt(areas, pt)
    if (!fam) { onError('Click inside a tool area to report a tool-down there.'); return }
    const n = state.scenario.jobs.length + 1
    act(() => reportJob(state.id, {
      id: `L${String(n).padStart(3, '0')}`, x: pt.x, y: pt.y, skill: fam, min_level: fam === 'litho' ? 2 : 1,
      priority: 3, kind: 'down', earliest: 0, latest: SLA[3], duration: 60, tool: `${fam.slice(0, 3).toUpperCase()}-LIVE`,
      symptom: 'operator reported tool down',
    }))
  }

  return (
    <>
      <section className="card live-bar">
        <div className="live-clock">
          <span className="eyebrow" style={{ margin: 0 }}>Shift clock</span>
          <strong className="num">{clock(state.clock)}</strong>
          <span className={`live-dot ${connected ? 'on' : ''}`} title={connected ? 'Live: receiving updates' : 'Reconnecting…'} />
          <span className="muted" style={{ fontSize: 12 }}>{connected ? 'live' : 'reconnecting'}</span>
        </div>
        <div className="live-track" aria-label={`Shift progress ${Math.round(pct)}%`}><span style={{ width: `${pct}%` }} /></div>
        <div className="live-controls">
          <button className="btn primary" onClick={() => setPlaying((p) => !p)} disabled={state.ended}>{playing ? 'Pause' : state.ended ? 'Ended' : 'Play'}</button>
          <div className="seg" role="group" aria-label="Speed">
            {SPEEDS.map(([v, l]) => <button key={v} aria-pressed={speed === v} onClick={() => setSpeed(v)}>{l}</button>)}
          </div>
          <button className="btn" disabled={busy || state.ended} onClick={() => act(() => advanceShift(state.id, 60))}>+1 h</button>
          <label className="toggle"><input type="checkbox" checked={reportMode} onChange={(e) => setReportMode(e.target.checked)} />Click floor to report a bottleneck down</label>
          <span className="spacer" />
          <button className="btn ghost" onClick={() => navigator.clipboard?.writeText(location.href)}>Copy share link</button>
          <button className="btn ghost" onClick={leave}>Leave</button>
        </div>
      </section>

      <div className="cards" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
        {[['Done', progress.done], ['In progress', progress.in_progress], ['Planned', progress.planned],
          ['Unassigned', progress.unassigned], ['Reported so far', `${progress.known}/${progress.total}`], ['Re-plans', state.replans]].map(([l, v]) => (
          <div key={l} className="card score"><div className="kpi"><div className="label">{l}</div><div className="value">{v}</div></div></div>
        ))}
      </div>
      {critOpen > 0 && <div className="error-bar" role="alert">⚠ {critOpen} bottleneck tool-down{critOpen > 1 ? 's are' : ' is'} unassigned. No qualified engineer can reach {critOpen > 1 ? 'them' : 'it'} within the window.</div>}

      <div className="floor-layout">
        <section className="card">
          <div className="floor-toolbar">
            <div><b>{plan?.label}</b> <span className="muted">· {plan?.metrics.assigned}/{plan?.metrics.jobs} known jobs planned · last re-plan {fmt(plan?.metrics.runtime_ms ?? 0, 0)} ms</span></div>
            <div className="legend-row" style={{ padding: 0 }}>
              <span><i className="lg circle o2" />Planned (shade = priority)</span>
              <span><i className="lg circle" style={{ background: 'var(--surface)', border: '2px solid var(--accent)' }} />In progress</span>
              <span><i className="lg circle" style={{ background: 'var(--surface-3)' }} />Done</span>
              <span><i className="lg un" />Unassigned</span>
            </div>
          </div>
          <div className="floor-wrap">
            <FloorPlan scenario={visible} result={plan} areas={areas} selection={selection} onSelect={setSelection}
              offShift={offShift} status={status} addMode={reportMode} onFloorClick={onFloor} />
          </div>
        </section>
        <section className="card feed" aria-label="Event feed" aria-live="polite">
          <div className="card-h"><div><h2>Dispatch log</h2><p>Every change, as it streams in.</p></div></div>
          {selection?.type === 'engineer' && (
            <div className="card-b" style={{ display: 'flex', gap: 8, alignItems: 'center', borderBottom: '1px solid var(--line)' }}>
              <b>{selection.id}</b>
              {offShift.has(selection.id)
                ? <span className="muted">left the shift at {clock(state.off_shift[selection.id])}</span>
                : <button className="btn" disabled={busy || state.ended} onClick={() => act(() => engineerOff(state.id, selection.id))}>Take off shift now</button>}
              <button className="btn ghost" onClick={() => setSelection(null)}>Clear</button>
            </div>
          )}
          <ol className="events">
            {feed.length === 0 && <li className="muted">Waiting for events…</li>}
            {feed.map((e) => (
              <li key={e.id} className={`ev ev-${e.kind}`}>
                <span className="num muted">{clock(e.clock)}</span>
                <span>{e.message}{e.kind === 'replanned' && e.data?.moved?.length > 0 && <span className="muted"> Moved: {e.data.moved.join(', ')}.</span>}</span>
              </li>
            ))}
          </ol>
        </section>
      </div>

      {plan && (
        <section className="card">
          <div className="card-h"><div><h2>Live schedule</h2><p>Locked work is solid; the vertical line is now.</p></div></div>
          <Schedule scenario={visible} result={plan} selection={selection} onSelect={setSelection} offShift={offShift} now={state.clock} />
        </section>
      )}
      {plan && plan.unassigned.length > 0 && (
        <section className="card">
          <div className="card-h"><div><h2>Unassigned now</h2></div></div>
          <div className="card-b table-wrap">
            <table className="data"><tbody>
              {plan.unassigned.map((u) => {
                const j = state.scenario.jobs.find((x) => x.id === u.job_id)
                return <tr key={u.job_id} style={{ cursor: 'default' }}><td><b>{u.job_id}</b> {j?.tool}</td><td><span className={`badge p${j?.priority}`}>{PRIORITY[j?.priority]?.label}</span></td><td>{u.reason}</td></tr>
              })}
            </tbody></table>
          </div>
        </section>
      )}
    </>
  )
}
