import { useCallback, useEffect, useRef, useState } from 'react'
import { advanceShift, createShift, engineerOff, getShift, listShifts, releaseClock, reportJob, streamUrl } from '../api.js'
import { useAuth } from '../auth.jsx'
import { ALGO_ORDER, ALGO_SHORT } from '../lib/metrics.js'
import { PRIORITY, clock, fmt } from '../lib/format.js'
import { familyAt, familyPrefix, isConstraint, shiftLength } from '../lib/fab.js'
import FloorPlan from './FloorPlan.jsx'
import Schedule from './Schedule.jsx'

const SPEEDS = [[5, '5 min/s'], [15, '15 min/s'], [30, '30 min/s']]
const SLA_BOTTLENECK = 45
const EVENT_KINDS = ['shift_started', 'job_reported', 'replanned', 'engineer_off', 'clock', 'clock_released', 'shift_ended']

function useOnline() {
  const [online, setOnline] = useState(() => navigator.onLine)
  useEffect(() => {
    const up = () => setOnline(true), down = () => setOnline(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    return () => { window.removeEventListener('online', up); window.removeEventListener('offline', down) }
  }, [])
  return online
}

function Toasts({ items, onDismiss }) {
  return (
    <div className="toasts" aria-live="assertive">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.tone}`} role="status">
          <span>{t.text}</span><button className="btn ghost" onClick={() => onDismiss(t.id)} aria-label="Dismiss">✕</button>
        </div>
      ))}
    </div>
  )
}

/**
 * Live dispatch. The shift lives on the server; this view drives the clock (dispatchers
 * only, one at a time via a lease) and listens on Server-Sent Events, so every open
 * dashboard (another tab, another device) sees each re-plan as it happens.
 */
export default function LiveShift({ scenario, weights, areas, profile, canDispatch, onError }) {
  const { user } = useAuth()
  const online = useOnline()
  const [algorithm, setAlgorithm] = useState('alns')
  const [shiftId, setShiftId] = useState(() => new URLSearchParams(location.search).get('shift'))
  const [view, setView] = useState(null)
  const [recent, setRecent] = useState([])
  const [feed, setFeed] = useState([])
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(15)
  const [busy, setBusy] = useState(false)
  const [connected, setConnected] = useState(false)
  const [selection, setSelection] = useState(null)
  const [reportMode, setReportMode] = useState(false)
  const [toasts, setToasts] = useState([])
  const etag = useRef(null)

  const toast = useCallback((text, tone = '') => {
    const id = Math.random().toString(36).slice(2)
    setToasts((t) => [...t.slice(-3), { id, text, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000)
  }, [])

  const refresh = useCallback(async (id) => {
    const r = await getShift(id, etag.current)
    if (r.notModified) return
    etag.current = r.etag
    setView(r.data)
  }, [])

  // Recent shifts for this fab, so anyone can rejoin a shift after closing the tab.
  useEffect(() => {
    if (shiftId) return
    listShifts(profile.id).then(setRecent).catch(() => setRecent([]))
  }, [shiftId, profile.id])

  useEffect(() => {
    if (!shiftId) return
    const url = new URL(location.href)
    url.searchParams.set('shift', shiftId)
    history.replaceState(null, '', url)
    etag.current = null // a cached ETag would get a 304 here, with no view to keep
    refresh(shiftId).catch((e) => { onError(e.message); setShiftId(null) })
  }, [shiftId, refresh, onError])

  // Realtime: the SSE stream relays the shift's event log; each event triggers a cheap
  // conditional refetch (ETag, so unchanged state costs a 304). A slow poll keeps
  // presence and the clock driver fresh even when nothing happens.
  useEffect(() => {
    if (!shiftId || !online) return
    const es = new EventSource(streamUrl(shiftId))
    const onEvent = (e) => {
      const ev = JSON.parse(e.data)
      setFeed((prev) => (prev.some((x) => x.id === ev.id) ? prev : [ev, ...prev].slice(0, 200)))
      if (ev.kind === 'job_reported' && ev.data?.priority === 3) toast(`Bottleneck down: ${ev.message}`, 'alert')
      if (ev.kind === 'engineer_off') toast(ev.message, 'alert')
      refresh(shiftId).catch(() => {})
    }
    EVENT_KINDS.forEach((k) => es.addEventListener(k, onEvent))
    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false) // EventSource reconnects by itself (Last-Event-ID)
    const poll = setInterval(() => refresh(shiftId).catch(() => {}), 15000)
    return () => { es.close(); clearInterval(poll) }
  }, [shiftId, refresh, online, toast])

  const act = useCallback(async (fn) => {
    setBusy(true)
    try {
      const out = await fn()
      if (out?.state) { setView(out); etag.current = null }
    } catch (e) {
      if (e.status === 409) toast(e.message)
      else onError(e.message)
      setPlaying(false)
    } finally {
      setBusy(false)
    }
  }, [onError, toast])

  const driver = view?.clock_driver
  const drivenByOther = Boolean(driver && driver !== user.email)

  // Autoplay: one request per second while this dispatcher holds the clock.
  useEffect(() => {
    if (!playing || !shiftId || view?.state.ended || !online) return
    const t = setInterval(() => { if (!busy) act(() => advanceShift(shiftId, speed)) }, 1000)
    return () => clearInterval(t)
  }, [playing, shiftId, speed, busy, view?.state.ended, online, act])
  useEffect(() => { if (view?.state.ended) setPlaying(false) }, [view?.state.ended])

  const pause = () => {
    setPlaying(false)
    if (shiftId) releaseClock(shiftId).catch(() => {})   // hand the clock back straight away
  }

  const start = () => act(async () => {
    const out = await createShift(scenario, weights, algorithm)
    setFeed([])
    etag.current = null
    setShiftId(out.state.id)
    return out
  })

  const leave = () => {
    if (playing) pause()
    setShiftId(null); setView(null); setFeed([]); etag.current = null
    const url = new URL(location.href); url.searchParams.delete('shift'); history.replaceState(null, '', url)
  }

  if (!shiftId || !view) {
    return (
      <>
        <section className="card">
          <div className="card-h"><div><h2><span className="section-no">01</span>Live dispatch</h2>
            <p>Run this shift in real time. Tool-downs are revealed when they happen (no peeking ahead), started work is locked, and the chosen strategy re-plans open work on every event. Changes stream to every open dashboard.</p></div></div>
          <div className="card-b" style={{ display: 'flex', gap: 12, alignItems: 'end', flexWrap: 'wrap' }}>
            <label className="field" style={{ margin: 0, width: 240 }}><span>Re-dispatch strategy</span>
              <select className="input" value={algorithm} onChange={(e) => setAlgorithm(e.target.value)}>
                {ALGO_ORDER.map((a) => <option key={a} value={a}>{ALGO_SHORT[a]}</option>)}
              </select>
            </label>
            <button className="btn primary" onClick={start} disabled={busy || !canDispatch}>{busy ? 'Starting…' : 'Start live shift'}</button>
            <span className="help" style={{ margin: 0 }}>
              {canDispatch ? `${scenario.engineers.length} engineers · ${scenario.jobs.length} jobs over the shift`
                : 'Starting a shift needs the dispatcher role. You can join and watch any shift below.'}
            </span>
          </div>
        </section>
        <section className="card">
          <div className="card-h"><div><h2><span className="section-no">02</span>Recent shifts · {profile.name}</h2><p>Rejoin a running shift or review a finished one.</p></div></div>
          <div className="card-b table-wrap">
            {recent.length === 0 ? <div className="empty">No shifts yet for this fab.</div> : (
              <table className="data">
                <thead><tr><th>Shift</th><th>Started by</th><th>Strategy</th><th className="r">Clock</th><th>Status</th><th /></tr></thead>
                <tbody>
                  {recent.map((r) => (
                    <tr key={r.id} onClick={() => setShiftId(r.id)}>
                      <td className="num"><b>{r.id}</b></td>
                      <td>{r.created_by || '—'}</td>
                      <td>{ALGO_SHORT[r.algorithm] ?? r.algorithm}</td>
                      <td className="r num">{clock(r.clock ?? 0)}</td>
                      <td>{r.ended ? <span className="badge">Ended</span> : <span className="badge p3">Running</span>}</td>
                      <td className="r"><button className="btn">Join</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>
      </>
    )
  }

  const { state, status, progress, viewers } = view
  const plan = state.plan
  const knownJobs = new Set(state.released)
  const visible = { ...state.scenario, jobs: state.scenario.jobs.filter((j) => knownJobs.has(j.id)) }
  const offShift = new Set(Object.keys(state.off_shift))
  const pct = (state.clock / shiftLength()) * 100
  const critOpen = state.scenario.jobs.filter((j) => knownJobs.has(j.id) && j.priority === 3 && status[j.id] === 'unassigned').length

  const onFloor = (pt) => {
    if (!reportMode || !canDispatch) return
    const fam = familyAt(pt)
    if (!fam) { onError('Tap inside a tool area to report a tool-down there.'); return }
    const n = state.scenario.jobs.length + 1
    act(() => reportJob(state.id, {
      id: `L${String(n).padStart(3, '0')}`, x: pt.x, y: pt.y, skill: fam, min_level: isConstraint(fam) ? 2 : 1,
      priority: 3, kind: 'down', earliest: 0, latest: SLA_BOTTLENECK, duration: 60, tool: `${familyPrefix(fam)}-LIVE`,
      symptom: 'operator reported tool down',
    }))
  }

  return (
    <>
      {!online && <div className="error-bar" role="alert">You're offline. The shift keeps its state on the server; this view resumes when you reconnect.</div>}
      <section className="card live-bar">
        <div className="live-clock">
          <span className="eyebrow" style={{ margin: 0 }}>Shift clock</span>
          <strong className="num">{clock(state.clock)}</strong>
          <span className={`live-dot ${connected && online ? 'on' : ''}`} title={connected ? 'Live: receiving updates' : 'Reconnecting…'} />
          <span className="muted" style={{ fontSize: 12 }}>{connected && online ? 'live' : 'reconnecting'}</span>
          <span className="spacer" />
          <span className="presence" title="Watching this shift now">
            {(viewers ?? []).slice(0, 5).map((v) => <span key={v} className="avatar sm" title={v}>{v[0]?.toUpperCase()}</span>)}
            <span className="muted">{(viewers ?? []).length} watching</span>
          </span>
        </div>
        <div className="live-track" aria-label={`Shift progress ${Math.round(pct)}%`}><span style={{ width: `${pct}%` }} /></div>
        <div className="live-controls">
          {canDispatch ? (
            <>
              <button className="btn primary" onClick={() => (playing ? pause() : setPlaying(true))}
                disabled={state.ended || (!playing && drivenByOther)}>{playing ? 'Pause' : state.ended ? 'Ended' : 'Play'}</button>
              <div className="seg" role="group" aria-label="Speed">
                {SPEEDS.map(([v, l]) => <button key={v} aria-pressed={speed === v} onClick={() => setSpeed(v)}>{l}</button>)}
              </div>
              <button className="btn" disabled={busy || state.ended || drivenByOther} onClick={() => act(() => advanceShift(state.id, 60))}>+1 h</button>
              <label className="toggle"><input type="checkbox" checked={reportMode} onChange={(e) => setReportMode(e.target.checked)} />Tap floor to report a bottleneck down</label>
            </>
          ) : <span className="badge">Viewing only</span>}
          {driver && <span className="help" style={{ margin: 0 }}>Clock driven by <b>{driver === user.email ? 'you' : driver}</b></span>}
          <span className="spacer" />
          <button className="btn ghost" onClick={() => { navigator.clipboard?.writeText(location.href); toast('Share link copied') }}>Copy link</button>
          <button className="btn ghost" onClick={leave}>Leave</button>
        </div>
      </section>

      <div className="cards" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))' }}>
        {[['Done', progress.done], ['In progress', progress.in_progress], ['Planned', progress.planned],
          ['Unassigned', progress.unassigned], ['Reported', `${progress.known}/${progress.total}`], ['Re-plans', state.replans]].map(([l, v]) => (
          <div key={l} className="card score"><div className="kpi"><div className="label">{l}</div><div className="value">{v}</div></div></div>
        ))}
      </div>
      {critOpen > 0 && <div className="error-bar" role="alert">⚠ {critOpen} bottleneck tool-down{critOpen > 1 ? 's are' : ' is'} unassigned. No qualified engineer can reach {critOpen > 1 ? 'them' : 'it'} within the window.</div>}

      <div className="floor-layout">
        <section className="card">
          <div className="floor-toolbar">
            <div><b>{plan?.label}</b> <span className="muted">· {plan?.metrics.assigned}/{plan?.metrics.jobs} known jobs planned · last re-plan {fmt(plan?.metrics.runtime_ms ?? 0, 0)} ms</span></div>
            <div className="legend-row" style={{ padding: 0 }}>
              <span><i className="lg circle o2" />Planned</span>
              <span><i className="lg circle" style={{ background: 'var(--surface)', border: '2px solid var(--signal)' }} />In progress</span>
              <span><i className="lg circle" style={{ background: 'var(--surface-3)' }} />Done</span>
              <span><i className="lg un" />Unassigned</span>
            </div>
          </div>
          <div className="floor-wrap">
            <FloorPlan scenario={visible} result={plan} areas={areas} selection={selection} onSelect={setSelection}
              offShift={offShift} status={status} addMode={reportMode && canDispatch} onFloorClick={onFloor} />
          </div>
        </section>
        <section className="card feed" aria-label="Dispatch log" aria-live="polite">
          <div className="card-h"><div><h2>Dispatch log</h2><p>Every change and who made it, as it streams in.</p></div></div>
          {selection?.type === 'engineer' && canDispatch && (
            <div className="card-b" style={{ display: 'flex', gap: 8, alignItems: 'center', borderBottom: '1px solid var(--line)', flexWrap: 'wrap' }}>
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
      <Toasts items={toasts} onDismiss={(id) => setToasts((t) => t.filter((x) => x.id !== id))} />
    </>
  )
}
