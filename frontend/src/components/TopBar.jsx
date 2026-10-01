import { useEffect, useRef, useState } from 'react'
import { ALGO_SHORT } from '../lib/metrics.js'
import { useAuth } from '../auth.jsx'

const THEMES = [['light', 'Light'], ['dark', 'Dark'], ['system', 'Auto']]

function ThemeSwitch({ theme, onTheme, className = '' }) {
  return (
    <div className={`seg theme-seg ${className}`} role="group" aria-label="Theme">
      {THEMES.map(([m, label]) => <button key={m} aria-pressed={theme === m} onClick={() => onTheme(m)}>{label}</button>)}
    </div>
  )
}

function UserMenu({ theme, onTheme }) {
  const { user, signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false) }
    const esc = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('pointerdown', close); document.removeEventListener('keydown', esc) }
  }, [open])
  return (
    <div className="user-menu" ref={ref}>
      <button className="avatar" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        title={`${user.email} · ${user.role}`}>{user.email[0]?.toUpperCase()}</button>
      {open && (
        <div className="menu card" role="menu">
          <div className="menu-h"><b>{user.email}</b><span className={`badge ${user.role === 'dispatcher' ? 'p3' : ''}`}>{user.role}</span></div>
          <p className="help" style={{ margin: '6px 0 10px' }}>
            {user.role === 'dispatcher' ? 'You can drive live shifts, report tool-downs and run benchmarks.'
              : 'You can plan and watch. Ask an admin for the dispatcher role to drive live shifts.'}
            {user.provider === 'guest' && ' This is a guest session: signing out ends it.'}
          </p>
          {/* On phones the theme switch lives here, where there's room for it. */}
          <div className="menu-theme"><span className="help">Theme</span><ThemeSwitch theme={theme} onTheme={onTheme} /></div>
          <button className="btn block" role="menuitem" onClick={signOut}>Sign out</button>
        </div>
      )}
    </div>
  )
}

export default function TopBar({ fabs, fabId, onFab, chips, busy, pending, solvedNote, theme, onTheme, onMenu, onHelp }) {
  return (
    <header className="topbar">
      <button className="btn ghost menu-btn" onClick={onMenu} aria-label="Open controls">☰</button>
      <div className="brand"><span className="brand-mark"><span /></span><span className="brand-name">Fab Dispatch</span></div>
      {fabs.length > 0 && (
        <select className="input fab-select" value={fabId} onChange={(e) => onFab(e.target.value)} aria-label="Fab">
          {fabs.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
        </select>
      )}
      <div className="context" aria-label="Current scenario">{chips}</div>
      <span className="spacer" />
      <span className="solve-state" aria-live="polite"><span className={`dot ${busy ? 'busy' : ''}`} />
        <span className="solve-text">{busy ? `Solving ${[...pending].map((a) => ALGO_SHORT[a]).join(', ')}…` : solvedNote}</span></span>
      <ThemeSwitch theme={theme} onTheme={onTheme} className="bar-theme" />
      <button className="btn ghost help-btn" onClick={onHelp} aria-label="Help" aria-keyshortcuts="?" title="Help (?)" data-tour="help">?</button>
      <UserMenu theme={theme} onTheme={onTheme} />
    </header>
  )
}
