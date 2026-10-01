// Supabase sign-in paths (guest, emailed one-time code or link) with a fake client.
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

  it('emails a code (and link) and accepts the code, whatever its length', async () => {
    supabaseApi()
    const user = renderApp()
    await user.type(await screen.findByLabelText('Email'), 'recruiter@company.com')
    await user.click(screen.getByRole('button', { name: 'Email me a sign-in code' }))
    expect(auth.signInWithOtp).toHaveBeenCalledWith({ email: 'recruiter@company.com', options: { emailRedirectTo: location.origin } })
    expect(await screen.findByRole('status')).toHaveTextContent('Code sent to recruiter@company.com')
    expect(screen.getByRole('button', { name: 'Send a new code' })).toBeInTheDocument()
    const verify = screen.getByRole('button', { name: 'Verify code' })
    expect(verify).toBeDisabled()
    const field = screen.getByLabelText('Code from the email')
    await user.type(field, '48a2-91')
    expect(field).toHaveValue('48291') // digits only
    expect(verify).toBeDisabled() // shorter than any Supabase code
    await user.type(field, '3671') // Supabase sends 6 to 10 digits; this project sends 8
    expect(field).toHaveValue('482913671')
    await user.click(verify)
    expect(auth.verifyOtp).toHaveBeenCalledWith({ email: 'recruiter@company.com', token: '482913671', type: 'email' })
    expect(await screen.findByRole('region', { name: 'Recommendation' }, { timeout: 4000 })).toBeInTheDocument()
  })

  it('shows a failure to send the code as an error, not a crash', async () => {
    supabaseApi()
    auth.signInWithOtp.mockResolvedValueOnce({ error: { message: 'Email rate limit exceeded' } })
    const user = renderApp()
    await user.type(await screen.findByLabelText('Email'), 'a@b.co')
    await user.click(screen.getByRole('button', { name: 'Email me a sign-in code' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Email rate limit exceeded')
    expect(screen.queryByLabelText('Code from the email')).not.toBeInTheDocument()
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

  it('sends a fresh token with every code request', async () => {
    supabaseApi('dispatcher', '0x4AAAAAAA-site')
    const user = renderApp()
    await user.type(await screen.findByLabelText('Email'), 'recruiter@company.com')
    await waitFor(() => expect(window.turnstile.render).toHaveBeenCalled())
    solve('cap-2')
    await user.click(screen.getByRole('button', { name: 'Email me a sign-in code' }))
    expect(auth.signInWithOtp).toHaveBeenCalledWith({ email: 'recruiter@company.com', options: { emailRedirectTo: location.origin, captchaToken: 'cap-2' } })
    solve('cap-3')
    await user.click(await screen.findByRole('button', { name: 'Send a new code' }))
    expect(auth.signInWithOtp).toHaveBeenLastCalledWith({ email: 'recruiter@company.com', options: { emailRedirectTo: location.origin, captchaToken: 'cap-3' } })
  })

  it('stays out of the way when CAPTCHA is off', async () => {
    supabaseApi('dispatcher', null)
    renderApp()
    expect(await screen.findByRole('button', { name: 'Try it as a guest' })).toBeEnabled()
    expect(window.turnstile.render).not.toHaveBeenCalled()
  })
})
