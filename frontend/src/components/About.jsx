import { useEffect, useState } from 'react'
import { getHealth, getMeta } from '../api.js'
import { LINKS, reportProblemUrl } from '../lib/links.js'

const ext = { target: '_blank', rel: 'noopener noreferrer' }
const STACK = ['React 19', 'FastAPI', 'PyVRP', 'SciPy (HiGHS)', 'Qdrant', 'Supabase', 'Vercel']

/** Version, live status, documentation and every way to get help, in one place. */
export default function About({ onClose, onHelp }) {
  const [health, setHealth] = useState(null)
  const [meta, setMeta] = useState(null)
  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth({ status: 'unreachable' }))
    getMeta().then(setMeta).catch(() => {})
  }, [])
  useEffect(() => {
    const esc = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [onClose])

  const ok = health?.status === 'ok'
  const release = health?.release ?? meta?.release
  const report = reportProblemUrl({ release, commit: health?.commit })
  return (
    <>
      <div className="backdrop help-backdrop" onClick={onClose} aria-hidden />
      <aside className="help-panel about" role="dialog" aria-modal="true" aria-label="About and support">
        <div className="help-h"><b>About &amp; support</b><span className="spacer" /><button className="btn ghost" onClick={onClose} aria-label="Close about">✕</button></div>
        <div className="help-body">
          <div className="about-hero">
            <span className="brand-mark"><span /></span>
            <div><h2 style={{ margin: 0 }}>Fab Dispatch</h2><p className="help" style={{ margin: 0 }}>Maintenance dispatch for semiconductor fabs</p></div>
          </div>

          <dl className="facts about-facts" aria-label="Version">
            <dt>Release</dt><dd className="num">{release ? `v${release}` : '…'}</dd>
            <dt>Engine</dt><dd className="num">{health?.version ?? '…'}</dd>
            <dt>Build</dt><dd className="num">{health?.commit ?? '…'}</dd>
            <dt>Environment</dt><dd>{health?.env ?? '…'}{meta?.store && ` · ${meta.store}`}</dd>
            <dt>Status</dt><dd><span role="status">{!health ? 'Checking…' : <span className={ok ? 'ok' : 'bad'}>{ok ? '● All systems operational' : `● ${health.status === 'unreachable' ? 'API unreachable' : 'Degraded'}`}</span>}</span></dd>
          </dl>

          <section className="help-section">
            <p className="eyebrow">Documentation</p>
            <ul className="help-list link-list">
              <li><button onClick={onHelp}><b>Help center</b><span className="help-snippet">Guides for every view, in the app. Press ?.</span></button></li>
              <li><a href={LINKS.docs} {...ext}><b>Documentation site ↗</b><span className="help-snippet">Architecture, algorithms, operations and decisions.</span></a></li>
              <li><a href={LINKS.apiReference} {...ext}><b>API reference ↗</b><span className="help-snippet">Interactive OpenAPI docs for every endpoint.</span></a></li>
              <li><a href={LINKS.changelog} {...ext}><b>What's new ↗</b><span className="help-snippet">Release notes for every version.</span></a></li>
            </ul>
          </section>

          <section className="help-section">
            <p className="eyebrow">Support</p>
            <ul className="help-list link-list">
              <li><a href={report} {...ext}><b>Report a problem ↗</b><span className="help-snippet">Opens a prefilled issue with your release and browser.</span></a></li>
              <li><a href={LINKS.discussions} {...ext}><b>Ask a question ↗</b><span className="help-snippet">Community Q&amp;A on GitHub Discussions.</span></a></li>
              <li><a href={LINKS.security} {...ext}><b>Report a security issue ↗</b><span className="help-snippet">Privately, through the security policy. Please don't open a public issue.</span></a></li>
              <li><a href={LINKS.privacy} {...ext}><b>Privacy and data ↗</b><span className="help-snippet">What's stored, for how long, and why.</span></a></li>
              <li><a href={LINKS.aiTransparency} {...ext}><b>How the assistant works ↗</b><span className="help-snippet">Sources, evaluation, limits.</span></a></li>
            </ul>
          </section>

          <p className="help">Built with {STACK.join(' · ')}. <a href={LINKS.source} {...ext}>Source on GitHub ↗</a></p>
        </div>
      </aside>
    </>
  )
}
