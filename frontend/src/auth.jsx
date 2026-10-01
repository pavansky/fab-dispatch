import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { authConfig, clearPlanCache, demoSignIn, getMe, setTokenProvider } from './api.js'

// Two sign-in modes behind one context:
//  - supabase (UAT/prod): Supabase Auth in the browser (magic link or password); the API
//    verifies Supabase's token. No password ever touches this app's servers.
//  - demo (local dev): one click as Dispatcher or Viewer; the API refuses this in production.

const AuthContext = createContext(null)
export const useAuth = () => useContext(AuthContext)

const DEMO_KEY = 'fab-dispatch-demo-token'
const store = {
  get: () => { try { return localStorage.getItem(DEMO_KEY) } catch { return null } },
  set: (t) => { try { t ? localStorage.setItem(DEMO_KEY, t) : localStorage.removeItem(DEMO_KEY) } catch { /* private mode */ } },
}

export function AuthProvider({ children }) {
  const [state, setState] = useState({ status: 'loading', user: null, config: null, error: null })
  const token = useRef(null)
  const supabase = useRef(null)
  setTokenProvider(() => token.current)

  const adopt = useCallback(async (accessToken) => {
    token.current = accessToken
    if (!accessToken) { clearPlanCache(); setState((s) => ({ ...s, status: 'signedOut', user: null })); return }
    try {
      const user = await getMe()
      setState((s) => ({ ...s, status: 'signedIn', user, error: null }))
    } catch (e) {
      token.current = null
      store.set(null)
      setState((s) => ({ ...s, status: 'signedOut', user: null, error: e.status === 401 ? null : e.message }))
    }
  }, [])

  useEffect(() => {
    let unsubscribe = () => {}
    authConfig().then(async (config) => {
      setState((s) => ({ ...s, config }))
      if (config.mode === 'supabase') {
        const { createClient } = await import('@supabase/supabase-js')   // only loaded where used
        const client = createClient(config.supabase_url, config.supabase_publishable_key, {
          auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
        })
        supabase.current = client
        const { data } = await client.auth.getSession()
        await adopt(data.session?.access_token ?? null)
        const sub = client.auth.onAuthStateChange((_event, session) => { adopt(session?.access_token ?? null) })
        unsubscribe = () => sub.data.subscription.unsubscribe()
      } else {
        // Local demo only: ?as=dispatcher|viewer signs in directly (for screenshots and e2e runs).
        const q = new URLSearchParams(location.search)
        const as = q.get('as')
        if (!store.get() && (as === 'dispatcher' || as === 'viewer')) {
          q.delete('as')
          history.replaceState(null, '', `${location.pathname}${q.toString() ? `?${q}` : ''}`)
          const { access_token } = await demoSignIn(as)
          store.set(access_token)
        }
        await adopt(store.get())
      }
    }).catch((e) => setState((s) => ({ ...s, status: 'error', error: e.message })))
    return () => unsubscribe()
  }, [adopt])

  // Any 401 from the API (expired or revoked session) signs the user out cleanly.
  useEffect(() => {
    const onExpired = () => { store.set(null); supabase.current?.auth.signOut(); adopt(null) }
    window.addEventListener('auth:expired', onExpired)
    return () => window.removeEventListener('auth:expired', onExpired)
  }, [adopt])

  const value = {
    ...state,
    canDispatch: state.user?.role === 'dispatcher',
    async signInDemo(role) {
      const { access_token } = await demoSignIn(role)
      store.set(access_token)
      await adopt(access_token)
    },
    async sendMagicLink(email) {
      const { error } = await supabase.current.auth.signInWithOtp({ email, options: { emailRedirectTo: location.origin } })
      if (error) throw error
    },
    async signInWithPassword(email, password) {
      const { error } = await supabase.current.auth.signInWithPassword({ email, password })
      if (error) throw error
    },
    async signOut() {
      store.set(null)
      await supabase.current?.auth.signOut()
      await adopt(null)
    },
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function SignIn() {
  const auth = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [usePassword, setUsePassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(auth.error)

  const run = async (fn) => {
    setBusy(true); setError(null); setMessage(null)
    try { await fn() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  return (
    <main className="signin">
      <div className="signin-card card">
        <div className="brand" style={{ marginBottom: 18 }}><span className="brand-mark"><span /></span>Fab Dispatch</div>
        <h1>Sign in</h1>
        <p className="help">Dispatch equipment engineers to tool-downs and PMs, and compare five allocation strategies live.</p>

        {auth.config?.mode === 'demo' && (
          <>
            <p className="eyebrow" style={{ marginTop: 18 }}>Local demo: choose a role</p>
            <div className="signin-roles">
              <button className="btn primary" disabled={busy} onClick={() => run(() => auth.signInDemo('dispatcher'))}>Continue as Dispatcher</button>
              <button className="btn" disabled={busy} onClick={() => run(() => auth.signInDemo('viewer'))}>Continue as Viewer</button>
            </div>
            <p className="help">Dispatchers drive live shifts, report tool-downs and run benchmarks. Viewers plan, explore and watch.
              Demo sign-in only exists in local development; deployments use real accounts.</p>
          </>
        )}

        {auth.config?.mode === 'supabase' && (
          <form onSubmit={(e) => { e.preventDefault(); run(async () => {
            if (usePassword) await auth.signInWithPassword(email, password)
            else { await auth.sendMagicLink(email); setMessage(`Check ${email} for a sign-in link.`) }
          }) }}>
            <label className="field" style={{ marginTop: 18 }}><span>Work email</span>
              <input className="input" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            {usePassword && (
              <label className="field"><span>Password</span>
                <input className="input" type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
              </label>
            )}
            <button className="btn primary block" disabled={busy}>{usePassword ? 'Sign in' : 'Email me a sign-in link'}</button>
            <button type="button" className="btn ghost block" style={{ marginTop: 6 }} onClick={() => setUsePassword((v) => !v)}>
              {usePassword ? 'Use a magic link instead' : 'Use a password instead'}
            </button>
          </form>
        )}

        {message && <p className="notice" role="status">{message}</p>}
        {error && <p className="error-bar" role="alert" style={{ marginTop: 12 }}>{error}</p>}
      </div>
    </main>
  )
}
