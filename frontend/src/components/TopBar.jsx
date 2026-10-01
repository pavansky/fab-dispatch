import { useEffect, useRef, useState } from 'react'
import { ALGO_SHORT } from '../lib/metrics.js'
import { useAuth } from '../auth.jsx'
import { deleteAccount } from '../api.js'

const THEMES = [['light', 'Light'], ['dark', 'Dark'], ['system', 'Auto']]

function ThemeSwitch({ theme, onTheme, className = '' }) {
  return (
    <div className={`seg theme-seg ${className}`} role="group" aria-label="Theme">
      {THEMES.map(([m, label]) => <button key={m} aria-pressed={theme === m} onClick={() => onTheme(m)}>{label}</button>)}
    </div>
  )
}

function UserMenu({ theme, onTheme, onAbout }) {
  const { user, signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleteError, setDeleteError] = useState(null)
  const ref = useRef(null)
  const removeAccount = async () => {
    setDeleteError(null)
    try {
      await deleteAccount()
      signOut()
    } catch (e) {
      setDeleteError(e.message)
    }
  }
  useEffect(() => {
    if (!open) { setConfirmDelete(false); return }
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
          <button className="btn block" role="menuitem" style={{ marginBottom: 6 }} onClick={() => { setOpen(false); onAbout() }}>About &amp; support</button>
          <button className="btn block" role="menuitem" onClick={signOut}>Sign out</button>
          {/* Two steps, so a stray click can't delete anything. */}
          {confirmDelete ? (
            <div className="menu-danger" role="group" aria-label="Delete account">
              <p className="help">Deletes your account and personal data. Shifts you ran stay, credited to &ldquo;a deleted user&rdquo;. This can&rsquo;t be undone.</p>
              <button className="btn block danger" role="menuitem" onClick={removeAccount}>Delete permanently</button>
              <button className="btn block ghost" role="menuitem" onClick={() => setConfirmDelete(false)}>Keep my account</button>
              {deleteError && <p className="error-bar" role="alert">{deleteError}</p>}
            </div>
          ) : (
            <button className="link-btn menu-delete" role="menuitem" onClick={() => setConfirmDelete(true)}>Delete my account…</button>
          )}
        </div>
      )}
    </div>
  )
}

export default function TopBar({ fabs, fabId, onFab, chips, busy, pending, solvedNote, theme, onTheme, onMenu, onHelp, onAbout }) {
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
      <UserMenu theme={theme} onTheme={onTheme} onAbout={onAbout} />
    </header>
  )
}
