// About & support, the crash screen, and feedback on assistant answers.
import { render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import ErrorBoundary from '../components/ErrorBoundary.jsx'
import { LINKS, REPO, reportProblemUrl } from '../lib/links.js'
import { fixtures } from './api.js'
import { signInAs } from './app.jsx'

describe('Deleting your account', () => {
  it('takes two deliberate steps, then deletes and signs you out', async () => {
    const { api, user } = await signInAs('dispatcher')
    await user.click(screen.getByRole('button', { name: 'D' }))
    await user.click(screen.getByRole('menuitem', { name: 'Delete my account…' }))
    await user.click(screen.getByRole('menuitem', { name: 'Keep my account' }))
    expect(screen.queryByRole('menuitem', { name: 'Delete permanently' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('menuitem', { name: 'Delete my account…' }))
    await user.click(screen.getByRole('menuitem', { name: 'Delete permanently' }))
    await waitFor(() => expect(api.fetchMock.mock.calls.some(([url, init]) => url.endsWith('/auth/me') && init?.method === 'DELETE')).toBe(true))
    expect(await screen.findByRole('button', { name: /dispatcher/i })).toBeInTheDocument()
  })
})

describe('About & support', () => {
  it('shows the release, live status, and every documentation and support link', async () => {
    const { user } = await signInAs('dispatcher')
    await user.click(screen.getByRole('button', { name: 'D' }))
    await user.click(screen.getByRole('menuitem', { name: 'About & support' }))
    const about = await screen.findByRole('dialog', { name: 'About and support' })
    expect(await within(about).findByText(`v${fixtures.health.release}`)).toBeInTheDocument()
    expect(within(about).getByRole('status')).toHaveTextContent('All systems operational')
    const href = (name) => within(about).getByRole('link', { name: new RegExp(`^${name}`) }).getAttribute('href')
    expect(href('Documentation site')).toBe(LINKS.docs)
    expect(href('API reference')).toBe('/api/docs')
    expect(href('Ask a question')).toBe(LINKS.discussions)
    expect(href('Report a security issue')).toBe(LINKS.security)
    expect(href('Privacy and data')).toBe(LINKS.privacy)
    expect(href('Terms of use')).toBe(LINKS.terms)
    const report = new URL(href('Report a problem'))
    expect(report.origin + report.pathname).toBe(`${REPO}/issues/new`)
    expect(report.searchParams.get('body')).toContain(`Release: ${fixtures.health.release}`)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'About and support' })).not.toBeInTheDocument()
  })

  it('is reachable from the help center too', async () => {
    const { user } = await signInAs('dispatcher')
    await user.keyboard('?')
    const help = await screen.findByRole('dialog', { name: 'Help' })
    await user.click(await within(help).findByRole('button', { name: 'About & support' }))
    expect(await screen.findByRole('dialog', { name: 'About and support' })).toBeInTheDocument()
  })

  it('says when the API is down', async () => {
    const { api, user } = await signInAs('dispatcher')
    api.fetchMock.mockImplementation(async () => { throw new TypeError('Failed to fetch') })
    await user.click(screen.getByRole('button', { name: 'D' }))
    await user.click(screen.getByRole('menuitem', { name: 'About & support' }))
    const about = await screen.findByRole('dialog', { name: 'About and support' })
    await waitFor(() => expect(within(about).getByRole('status')).toHaveTextContent('API unreachable'))
  })
})

describe('crash screen', () => {
  it('replaces a render error with a way forward and a prefilled report', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const Boom = () => { throw new Error('floor plan exploded') }
    render(<ErrorBoundary><Boom /></ErrorBoundary>)
    expect(screen.getByRole('heading', { name: 'Something went wrong' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
    const url = new URL(screen.getByRole('link', { name: 'Report this problem' }).getAttribute('href'))
    expect(url.searchParams.get('title')).toBe('UI error: floor plan exploded')
    expect(url.searchParams.get('body')).toContain('Error: `floor plan exploded`')
  })

  it('builds reports that never exceed what a URL can carry', () => {
    const url = new URL(reportProblemUrl({ error: 'x'.repeat(5000) }))
    expect(url.searchParams.get('body').length).toBeLessThan(1200)
  })
})

describe('answer feedback', () => {
  async function askOne(question) {
    const ctx = await signInAs('dispatcher')
    await waitFor(() => expect(ctx.api.find('POST', '/plan')).toHaveLength(5))
    await ctx.user.click(screen.getByRole('button', { name: 'Ask the assistant' }))
    const panel = await screen.findByRole('dialog', { name: 'Assistant' })
    await ctx.user.type(within(panel).getByRole('textbox', { name: 'Your question' }), `${question}{Enter}`)
    await within(panel).findByLabelText('Rate this answer')
    return { ...ctx, panel }
  }

  it('records a thumbs-up with what was asked and cited', async () => {
    const { api, user, panel } = await askOne('Why is J006 assigned this way?')
    await user.click(within(panel).getByRole('button', { name: 'Helpful' }))
    expect(await within(panel).findByText('Thanks for the feedback.')).toBeInTheDocument()
    const sent = api.find('POST', '/assistant/feedback')[0].body
    expect(sent).toMatchObject({ question: 'Why is J006 assigned this way?', intent: fixtures.askJob.intent, helpful: true, provider: 'local' })
    expect(sent.citations).toEqual(fixtures.askJob.citations.map((c) => c.slug))
  })

  it('asks what was wrong on a thumbs-down, optionally', async () => {
    const { api, user, panel } = await askOne('Tell me a joke')
    await user.click(within(panel).getByRole('button', { name: 'Not helpful' }))
    await user.type(within(panel).getByRole('textbox', { name: 'What was wrong with this answer?' }), 'I wanted a joke{Enter}')
    expect(await within(panel).findByText('Thanks for the feedback.')).toBeInTheDocument()
    expect(api.find('POST', '/assistant/feedback')[0].body).toMatchObject({ helpful: false, comment: 'I wanted a joke', intent: 'unknown' })
  })
})

describe('sign-in footer', () => {
  it('links to documentation, privacy, support and the source', async () => {
    const { mockApi, workspaceRoutes } = await import('./api.js')
    const { renderApp } = await import('./app.jsx')
    mockApi(workspaceRoutes())
    renderApp()
    const footer = await screen.findByRole('navigation', { name: 'About Fab Dispatch' })
    expect(within(footer).getAllByRole('link').map((a) => a.textContent)).toEqual(['Documentation', 'Privacy', 'Terms', 'Support', 'GitHub'])
  })
})
