// Supabase sign-in paths (guest, magic link + 6-digit code, password) with a fake client.
import { act, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fixtures, mockApi, workspaceRoutes } from './api.js'
import { renderApp } from './app.jsx'

const auth = vi.hoisted(() => ({}))
vi.mock('@supabase/supabase-js', () => ({ createClient: () => ({ auth }) }))

let listener
const signIn = (token) => listener?.('SIGNED_IN', { access_token: token })

beforeEach(() => {
  listener = null
  Object.assign(auth, {
    getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
    onAuthStateChange: vi.fn((cb) => { listener = cb; return { data: { subscription: { unsubscribe() {} } } } }),
    signInAnonymously: vi.fn(async () => { signIn('guest-token'); return { error: null } }),
    signInWithOtp: vi.fn().mockResolvedValue({ error: null }),
    verifyOtp: vi.fn(async () => { signIn('email-token'); return { error: null } }),
    signInWithPassword: vi.fn().mockResolvedValue({ error: { message: 'Invalid login credentials' } }),
    signOut: vi.fn().mockResolvedValue({ error: null }),
  })
})

function supabaseApi(guest_role = 'dispatcher', captcha_site_key = null) {
  const routes = workspaceRoutes()
  return mockApi({
    ...routes,
    'GET /auth/config': { mode: 'supabase', supabase_url: 'https://example.supabase.co', supabase_publishable_key: 'sb_publishable_test', guest_role, captcha_site_key },
    'GET /auth/me': ({ headers }) => (headers.Authorization === 'Bearer guest-token'
      ? { id: 'anon-1', email: 'guest-8f2c1e', role: guest_role, fabs: ['*'], provider: 'guest' }
      : { ...fixtures.me, email: 'recruiter@company.com', role: 'viewer', provider: 'supabase' }),
  })
}

describe('Supabase sign-in', () => {
  it('lets a guest in with one click, as the configured role', async () => {
    const api = supabaseApi('dispatcher')
    const user = renderApp()
    await user.click(await screen.findByRole('button', { name: 'Try it as a guest' }))
    expect(auth.signInAnonymously).toHaveBeenCalledOnce()
    expect(await screen.findByRole('region', { name: 'Recommendation' }, { timeout: 4000 })).toBeInTheDocument()
    expect(api.find('GET', '/auth/me').at(-1).headers.Authorization).toBe('Bearer guest-token')
    await user.click(screen.getByRole('button', { name: 'G' }))
    expect(screen.getByRole('menu')).toHaveTextContent('guest session')
  })

  it('emails a link and accepts the 6-digit code from it instead', async () => {
    supabaseApi()
    const user = renderApp()
    await user.type(await screen.findByLabelText('Work email'), 'recruiter@company.com')
    await user.click(screen.getByRole('button', { name: 'Email me a sign-in link' }))
    expect(auth.signInWithOtp).toHaveBeenCalledWith({ email: 'recruiter@company.com', options: { emailRedirectTo: location.origin } })
    expect(await screen.findByRole('status')).toHaveTextContent('enter the 6-digit code')
    const verify = screen.getByRole('button', { name: 'Verify code' })
    expect(verify).toBeDisabled()
    await user.type(screen.getByLabelText('6-digit code'), '48a2-913')
    expect(screen.getByLabelText('6-digit code')).toHaveValue('482913') // digits only
    await user.click(verify)
    expect(auth.verifyOtp).toHaveBeenCalledWith({ email: 'recruiter@company.com', token: '482913', type: 'email' })
    expect(await screen.findByRole('region', { name: 'Recommendation' }, { timeout: 4000 })).toBeInTheDocument()
  })

  it('shows a wrong password as an error, not a crash', async () => {
    supabaseApi()
    const user = renderApp()
    await user.click(await screen.findByRole('button', { name: 'Use a password instead' }))
    await user.type(screen.getByLabelText('Work email'), 'a@b.co')
    await user.type(screen.getByLabelText('Password'), 'nope')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid login credentials')
  })

  it('signs out of Supabase too', async () => {
    supabaseApi()
    const user = renderApp()
    await user.click(await screen.findByRole('button', { name: 'Try it as a guest' }))
    await screen.findByRole('region', { name: 'Recommendation' }, { timeout: 4000 })
    await user.click(screen.getByRole('button', { name: 'G' }))
    await user.click(screen.getByRole('menuitem', { name: 'Sign out' }))
    await waitFor(() => expect(auth.signOut).toHaveBeenCalled())
    expect(await screen.findByRole('button', { name: 'Try it as a guest' })).toBeInTheDocument()
  })
})

describe('CAPTCHA (Cloudflare Turnstile)', () => {
  let widget
  beforeEach(() => {
    widget = null
    window.turnstile = {
      render: vi.fn((el, opts) => { widget = opts; return 'w1' }),
      reset: vi.fn(),
      remove: vi.fn(),
    }
    return () => { delete window.turnstile }
  })
  const solve = (token) => act(() => widget.callback(token))

  it('waits for a CAPTCHA token, then sends it with the guest sign-in', async () => {
    supabaseApi('dispatcher', '0x4AAAAAAA-site')
    const user = renderApp()
    const guest = await screen.findByRole('button', { name: 'Try it as a guest' })
    await waitFor(() => expect(window.turnstile.render).toHaveBeenCalled())
    expect(widget.sitekey).toBe('0x4AAAAAAA-site')
    expect(guest).toBeDisabled()
    expect(screen.getByText('Checking your browser…')).toBeInTheDocument()
    solve('cap-1')
    expect(guest).toBeEnabled()
    await user.click(guest)
    expect(auth.signInAnonymously).toHaveBeenCalledWith({ options: { captchaToken: 'cap-1' } })
    await waitFor(() => expect(window.turnstile.reset).toHaveBeenCalledWith('w1')) // tokens are single-use
  })

  it('sends the token with the magic link and the password sign-in', async () => {
    supabaseApi('dispatcher', '0x4AAAAAAA-site')
    const user = renderApp()
    await user.type(await screen.findByLabelText('Work email'), 'recruiter@company.com')
    await waitFor(() => expect(window.turnstile.render).toHaveBeenCalled())
    solve('cap-2')
    await user.click(screen.getByRole('button', { name: 'Email me a sign-in link' }))
    expect(auth.signInWithOtp).toHaveBeenCalledWith({ email: 'recruiter@company.com', options: { emailRedirectTo: location.origin, captchaToken: 'cap-2' } })
    solve('cap-3')
    await user.click(screen.getByRole('button', { name: 'Use a password instead' }))
    await user.type(screen.getByLabelText('Password'), 'pw')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(auth.signInWithPassword).toHaveBeenCalledWith({ email: 'recruiter@company.com', password: 'pw', options: { captchaToken: 'cap-3' } })
  })

  it('stays out of the way when CAPTCHA is off', async () => {
    supabaseApi('dispatcher', null)
    renderApp()
    expect(await screen.findByRole('button', { name: 'Try it as a guest' })).toBeEnabled()
    expect(window.turnstile.render).not.toHaveBeenCalled()
  })
})
