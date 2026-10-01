import { useEffect, useLayoutEffect, useState } from 'react'

const STEPS = [
  { target: 'reco', title: 'The recommendation', body: 'All five strategies solve your shift. This card names the plan to use and says why in one sentence.' },
  { target: 'frontier', title: 'Cost against speed', body: 'Each point is a strategy. Lower-left is better. Differences inside the shaded band are noise, not wins.' },
  { target: 'tabs', title: 'Six views of one shift', body: 'Inspect jobs on the floor plan, timelines, staffing, run the shift live, or benchmark over many shifts.' },
  { target: 'weights', title: 'Tune what matters', body: 'Drag a cost weight and every strategy re-solves. Generate a new shift or try what-ifs here too.' },
  { target: 'ask', title: 'Ask anything', body: 'The assistant answers about this shift and the app, with sources. Press / any time.' },
  { target: 'help', title: 'Help is one key away', body: 'Press ? for help articles and shortcuts. You can replay this tour from there.' },
]

const visible = (el) => {
  if (!el) return false
  const r = el.getBoundingClientRect()
  return r.width > 0 && r.height > 0 && r.right > 0 && r.left < window.innerWidth
}

/** First-run walkthrough: spotlights one part of the workspace at a time. */
export default function Tour({ onDone }) {
  // Steps whose target isn't on screen (e.g. the sidebar inside the phone drawer) are skipped.
  const [steps] = useState(() => STEPS.filter((s) => visible(document.querySelector(`[data-tour="${s.target}"]`))))
  const [i, setI] = useState(0)
  const [rect, setRect] = useState(null)
  const step = steps[i]

  useLayoutEffect(() => {
    if (!step) return
    const el = document.querySelector(`[data-tour="${step.target}"]`)
    el?.scrollIntoView?.({ block: 'center' })
    const measure = () => { const r = el?.getBoundingClientRect(); setRect(r ? { top: r.top, left: r.left, width: r.width, height: r.height } : null) }
    measure()
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => { window.removeEventListener('resize', measure); window.removeEventListener('scroll', measure, true) }
  }, [step])

  useEffect(() => {
    const key = (e) => {
      if (e.key === 'Escape') onDone()
      if (e.key === 'ArrowRight') setI((n) => Math.min(n + 1, steps.length - 1))
      if (e.key === 'ArrowLeft') setI((n) => Math.max(n - 1, 0))
    }
    document.addEventListener('keydown', key)
    return () => document.removeEventListener('keydown', key)
  }, [steps.length, onDone])

  useEffect(() => { if (!steps.length) onDone() }, [steps.length, onDone])
  if (!step) return null

  const pad = 6
  const below = !rect || rect.top + rect.height + 200 < window.innerHeight
  const cardTop = rect ? (below ? rect.top + rect.height + 14 : Math.max(12, rect.top - 14 - 180)) : 80
  const cardLeft = rect ? Math.min(Math.max(12, rect.left), window.innerWidth - 332) : 12
  const last = i === steps.length - 1

  return (
    <div className="tour" role="dialog" aria-modal="true" aria-label="Tour">
      {rect && <div className="tour-spot" style={{ top: rect.top - pad, left: rect.left - pad, width: rect.width + 2 * pad, height: rect.height + 2 * pad }} />}
      <div className="tour-card card" style={{ top: cardTop, left: cardLeft }}>
        <p className="eyebrow">Step {i + 1} of {steps.length}</p>
        <h3>{step.title}</h3>
        <p>{step.body}</p>
        <div className="tour-actions">
          <button className="btn ghost" onClick={onDone}>Skip tour</button>
          <span className="spacer" />
          {i > 0 && <button className="btn" onClick={() => setI(i - 1)}>Back</button>}
          <button className="btn primary" onClick={() => (last ? onDone() : setI(i + 1))}>{last ? 'Done' : 'Next'}</button>
        </div>
      </div>
    </div>
  )
}
