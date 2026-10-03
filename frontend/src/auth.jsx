import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { authConfig, clearPlanCache, demoSignIn, getMe, setTokenProvider } from './api.js'
import { loadTurnstile } from './lib/captcha.js'
import { LINKS } from './lib/links.js'

// Two sign-in modes behind one context:
//  - supabase (UAT/prod): Supabase Auth in the browser, passwordless: a one-time code (and link)
//    by email, or guest access. There is no sign-up and no password to forget: the first
//    sign-in creates the account. The API verifies Supabase's token.
//  - demo (local dev): one click as Dispatcher or Viewer; the API refuses this in production.

const AuthContext = createContext(null)
export const useAuth = () => useContext(AuthContext)

const DEMO_KEY = 'fab-dispatch-demo-token'
const store = {
  get: () => { try { return localStorage.getItem(DEMO_KEY) } catch { return null } },
  set: (t) => { try { t ? localStorage.setItem(DEMO_KEY, t) : localStorage.removeItem(DEMO_KEY) } catch { /* private mode */ } },
}
const CONFIG_KEY = 'fab-dispatch-auth-config'
const configCache = {
  get: () => { try { return JSON.parse(localStorage.getItem(CONFIG_KEY)) } catch { return null } },
  set: (c) => { try { localStorage.setItem(CONFIG_KEY, JSON.stringify(c)) } catch { /* private mode */ } },
}

export function AuthProvider({ children }) {
  const [state, setState] = useState({ status: 'loading', user: null, config: null, error: null })
  const token = useRef(null)
  const signedIn = useRef(false)
  const supabase = useRef(null)
  setTokenProvider(() => token.current)

  const adopt = useCallback(async (accessToken) => {
    // Supabase announces the same session more than once (the stored session, then
    // INITIAL_SESSION). Checking the user again for an unchanged token is a wasted round trip.
    if (accessToken && accessToken === token.current && signedIn.current) return
    token.current = accessToken
    if (!accessToken) { signedIn.current = false; clearPlanCache(); setState((s) => ({ ...s, status: 'signedOut', user: null })); return }
    try {
      const user = await getMe()
      signedIn.current = true
      setState((s) => ({ ...s, status: 'signedIn', user, error: null }))
    } catch (e) {
      token.current = null
      signedIn.current = false
      store.set(null)
      setState((s) => ({ ...s, status: 'signedOut', user: null, error: e.status === 401 ? null : e.message }))
    }
  }, [])

  useEffect(() => {
    let unsubscribe = () => {}
    // The sign-in configuration rarely changes, so start from the last one this browser saw
    // and refresh it in the background: a cold server no longer blocks the first paint.
    const cached = configCache.get()
    const fresh = authConfig().then((config) => { configCache.set(config); return config })
    if (cached?.mode === 'supabase') import('@supabase/supabase-js')   // fetch the client in parallel
    ;(cached ? Promise.resolve(cached) : fresh).then(async (config) => {
      setState((s) => ({ ...s, config }))
      if (cached) fresh.then((latest) => setState((s) => ({ ...s, config: latest }))).catch(() => {})
      if (config.mode === 'supabase') {
        const { createClient } = await import('@supabase/supabase-js')   // only loaded where used
        const client = createClient(config.supabase_url, config.supabase_publishable_key, {
          auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
        })
        supabase.current = client
        const { data } = await client.auth.getSession()
        await adopt(data.session?.access_token ?? null)
        const sub = client.auth.onAuthStateChange((event, session) => {
          if (event === 'TOKEN_REFRESHED') { token.current = session?.access_token ?? null; return }   // same user
          adopt(session?.access_token ?? null)
        })
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
    // captchaToken is required by Supabase when CAPTCHA protection is on (see Captcha below).
    async sendMagicLink(email, captchaToken) {
      const { error } = await supabase.current.auth.signInWithOtp({ email, options: { emailRedirectTo: location.origin, ...(captchaToken && { captchaToken }) } })
      if (error) throw error
    },
    async verifyCode(email, token) {
      const { error } = await supabase.current.auth.verifyOtp({ email, token, type: 'email' })
      if (error) throw error
    },
    async signInAsGuest(captchaToken) {
      const { error } = await supabase.current.auth.signInAnonymously(captchaToken ? { options: { captchaToken } } : undefined)
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

/** Turnstile widget: usually invisible, shows a check only when Cloudflare wants one. */
function Captcha({ siteKey, onToken, resetRef }) {
  const box = useRef(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    let id = null
    let live = true
    loadTurnstile().then((ts) => {
      if (!live || !box.current) return
      id = ts.render(box.current, {
        sitekey: siteKey, appearance: 'interaction-only', theme: 'light', size: 'flexible',
        callback: (t) => onToken(t), 'expired-callback': () => onToken(null), 'error-callback': () => onToken(null),
      })
      resetRef.current = () => { onToken(null); ts.reset(id) } // tokens are single-use
    }).catch((e) => live && setError(e.message))
    return () => { live = false; if (id !== null) window.turnstile?.remove(id) }
  }, [siteKey, onToken, resetRef])
  return (
    <div className="captcha">
      <div ref={box} />
      {error && <p className="error-bar" role="alert">{error}</p>}
    </div>
  )
}

export function SignIn() {
  const auth = useAuth()
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const [sentTo, setSentTo] = useState(null) // email a link and code were sent to
  const [code, setCode] = useState('')
  const siteKey = auth.config?.mode === 'supabase' ? auth.config.captcha_site_key : null
  const [captcha, setCaptcha] = useState(null)
  const resetCaptcha = useRef(() => {})
  const needsCaptcha = Boolean(siteKey) && !captcha
  const [error, setError] = useState(auth.error)

  const run = async (fn) => {
    setBusy(true); setError(null); setMessage(null)
    try { await fn() } catch (e) { setError(e.message) } finally { setBusy(false); if (siteKey) resetCaptcha.current() }
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

        {auth.config?.mode === 'supabase' && auth.config.guest_role && (
          <div className="signin-guest">
            <button className="btn primary block" disabled={busy || needsCaptcha} onClick={() => run(() => auth.signInAsGuest(captcha))}>Try it as a guest</button>
            <p className="help">No email needed. Guests get {auth.config.guest_role === 'dispatcher' ? 'full dispatcher access' : 'read-only access'} to the sample fabs.</p>
            <div className="or"><span>or sign in with email</span></div>
          </div>
        )}

        {auth.config?.mode === 'supabase' && (
          <form onSubmit={(e) => { e.preventDefault(); run(async () => {
            await auth.sendMagicLink(email, captcha); setSentTo(email); setCode('')
            setMessage(`Code sent to ${email}. Enter it below, or open the link in the email.`)
          }) }}>
            <label className="field" style={{ marginTop: 18 }}><span>Email</span>
              <input className="input" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <p className="help" id="signin-how">New or returning, it&rsquo;s the same step: we email you a one-time code. No password and no sign-up.</p>
            <button className={`btn block ${auth.config.guest_role ? '' : 'primary'}`} disabled={busy || needsCaptcha} aria-describedby="signin-how">
              {sentTo ? 'Send a new code' : 'Email me a sign-in code'}
            </button>
          </form>
        )}

        {siteKey && <Captcha siteKey={siteKey} onToken={setCaptcha} resetRef={resetCaptcha} />}
        {needsCaptcha && <p className="help" style={{ marginTop: 8 }}>Checking your browser…</p>}
        {message && <p className="notice" role="status">{message}</p>}
        {sentTo && (
          <form className="signin-code" onSubmit={(e) => { e.preventDefault(); run(() => auth.verifyCode(sentTo, code.trim())) }}>
            {/* Supabase's code length is a project setting (6 to 10 digits), so accept that range. */}
            <label className="field"><span>Code from the email</span>
              <input className="input code-input" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6,10}" maxLength={10}
                required value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} />
            </label>
            <button className="btn primary block" disabled={busy || code.length < 6}>Verify code</button>
          </form>
        )}
        {error && <p className="error-bar" role="alert" style={{ marginTop: 12 }}>{error}</p>}
      </div>
      <nav className="signin-footer" aria-label="About Fab Dispatch">
        <a href={LINKS.docs} target="_blank" rel="noopener noreferrer">Documentation</a>
        <a href={LINKS.privacy} target="_blank" rel="noopener noreferrer">Privacy</a>
        <a href={LINKS.terms} target="_blank" rel="noopener noreferrer">Terms</a>
        <a href={LINKS.support} target="_blank" rel="noopener noreferrer">Support</a>
        <a href={LINKS.source} target="_blank" rel="noopener noreferrer">GitHub</a>
      </nav>
    </main>
  )
}
