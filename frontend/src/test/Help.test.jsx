// Help center, contextual help, the assistant and keyboard shortcuts, against real API
// responses (help articles and assistant answers exported from the backend).
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { errorBody, fixtures, json, workspaceRoutes } from './api.js'
import { signInAs } from './app.jsx'

const sources = import.meta.glob('../components/*.jsx', { query: '?raw', import: 'default', eager: true })

describe('contextual help links', () => {
  it('every ⓘ in the app points at a real article and section', () => {
    const links = Object.entries(sources).flatMap(([file, src]) =>
      [...src.matchAll(/<InfoLink slug="([^"]+)"(?: anchor="([^"]*)")?/g)].map(([, slug, anchor = '']) => ({ file, slug, anchor })))
    expect(links.length).toBeGreaterThan(8)
    for (const { file, slug, anchor } of links) {
      expect(fixtures.helpAnchors, `${file}: unknown article ${slug}`).toHaveProperty(slug)
      if (anchor) expect(fixtures.helpAnchors[slug], `${file}: unknown section ${slug}#${anchor}`).toContain(anchor)
    }
  })

  it('opens the help center at the section about that control', async () => {
    const { api, user } = await signInAs('dispatcher')
    await user.click(screen.getByRole('button', { name: 'Help: Cost weights' }))
    const help = await screen.findByRole('dialog', { name: 'Help' })
    expect(await within(help).findByRole('heading', { name: 'Constraints and cost weights' })).toBeInTheDocument()
    expect(api.find('GET', '/help/constraints-and-weights')).toHaveLength(1)
    expect(new URL(location.href).searchParams.get('help')).toBe('constraints-and-weights#soft-constraints-the-cost-weights')
  })
})

describe('help center', () => {
  it('opens with ? and lists every section and article', async () => {
    const { user } = await signInAs('dispatcher')
    await user.keyboard('?')
    const help = await screen.findByRole('dialog', { name: 'Help' })
    for (const s of fixtures.helpIndex.sections) {
      expect((await within(help).findAllByText(s.name)).length).toBeGreaterThan(0)
      for (const a of s.articles) expect(within(help).getByRole('button', { name: new RegExp(`^${a.title}`) })).toBeInTheDocument()
    }
    expect(within(help).getByRole('searchbox', { name: 'Search help' })).toHaveFocus()
  })

  it('renders an article from Markdown, with sections and working links between articles', async () => {
    const { api, user } = await signInAs('dispatcher')
    await user.click(screen.getByRole('button', { name: 'Help' }))
    const help = await screen.findByRole('dialog', { name: 'Help' })
    await user.click(await within(help).findByRole('button', { name: /^The six views/ }))
    expect(await within(help).findByRole('heading', { level: 2, name: 'The six views' })).toBeInTheDocument()
    expect(within(help).getByRole('heading', { level: 3, name: 'Floor plan' })).toHaveAttribute('id', 'floor-plan')
    await user.click(within(help).getByRole('link', { name: 'Reading the floor plan' }))
    expect(await within(help).findByRole('heading', { level: 2, name: 'Reading the floor plan' })).toBeInTheDocument()
    expect(api.find('GET', '/help/floor-plan')).toHaveLength(1)
    await user.click(within(help).getByRole('button', { name: '← All help' }))
    expect(await within(help).findByText('Get started')).toBeInTheDocument()
  })

  it('searches as you type and opens a result', async () => {
    const { api, user } = await signInAs('dispatcher')
    await user.keyboard('?')
    const help = await screen.findByRole('dialog', { name: 'Help' })
    await user.type(within(help).getByRole('searchbox', { name: 'Search help' }), 'idle wait')
    const results = await within(help).findByRole('list', { name: 'Search results' })
    const top = fixtures.helpSearch.results[0]
    await user.click(within(results).getAllByRole('button')[0])
    expect(await within(help).findByRole('heading', { level: 2, name: fixtures.helpArticles[top.slug].title })).toBeInTheDocument()
    expect(api.find('GET', '/help/search').at(-1).url).toContain('q=idle%20wait')
  })

  it('opens from a shared ?help= link and closes with Escape', async () => {
    history.replaceState(null, '', '/?help=live-dispatch')
    const { user } = await signInAs('dispatcher')
    const help = await screen.findByRole('dialog', { name: 'Help' })
    expect(await within(help).findByRole('heading', { level: 2, name: 'Live dispatch' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Help' })).not.toBeInTheDocument()
    expect(new URL(location.href).searchParams.has('help')).toBe(false)
  })
})

describe('assistant', () => {
  async function openAssistant(role = 'dispatcher', routes) {
    const ctx = await signInAs(role, routes)
    await waitFor(() => expect(ctx.api.find('POST', '/plan')).toHaveLength(5))
    await ctx.user.click(screen.getByRole('button', { name: 'Ask the assistant' }))
    return { ...ctx, panel: await screen.findByRole('dialog', { name: 'Assistant' }) }
  }

  it('opens with / and suggests questions about what is on screen', async () => {
    const { user } = await signInAs('dispatcher')
    await user.keyboard('/')
    const panel = await screen.findByRole('dialog', { name: 'Assistant' })
    const suggested = within(within(panel).getByLabelText('Suggested questions')).getAllByRole('button').map((b) => b.textContent)
    expect(suggested).toContain('Which jobs are unassigned?')
    expect(suggested.some((s) => /^Why is .+ recommended\?$/.test(s))).toBe(true)
    expect(within(panel).getByRole('textbox', { name: 'Your question' })).toHaveFocus()
  })

  it('sends the question with exactly what is on screen', async () => {
    const { api, user, panel } = await openAssistant()
    await user.type(within(panel).getByRole('textbox', { name: 'Your question' }), 'Why is J006 assigned this way?{Enter}')
    await within(panel).findByText(/Open J006 on the floor plan/)
    const sent = api.find('POST', '/assistant/ask')[0].body
    expect(sent.question).toBe('Why is J006 assigned this way?')
    expect(sent.context.fab_id).toBe(fixtures.fab1.id)
    expect(sent.context.scenario.jobs).toHaveLength(fixtures.scenario.jobs.length)
    expect(sent.context.weights).toEqual(fixtures.meta.default_weights)
    expect(sent.context.recommendation.algorithm).toBeTruthy()
    expect(sent.context.tab).toBe('overview')
  })

  it('shows a grounded answer with its sources, and acts on it', async () => {
    const { user, panel } = await openAssistant()
    await user.type(within(panel).getByRole('textbox', { name: 'Your question' }), 'Why is J006 assigned this way?{Enter}')
    const log = within(panel).getByRole('list', { name: 'Conversation' })
    expect(await within(log).findByText('Why is J006 assigned this way?')).toBeInTheDocument()
    for (const c of fixtures.askJob.citations) {
      expect(within(log).getByRole('button', { name: new RegExp(`^${c.title}`) })).toBeInTheDocument()
    }
    await user.click(within(log).getByRole('button', { name: 'Open J006 on the floor plan' }))
    expect(screen.getByRole('tab', { name: /Floor plan/ })).toHaveAttribute('aria-selected', 'true')
    expect(within(screen.getByRole('complementary', { name: 'Inspector' })).getByRole('heading', { level: 3 })).toHaveTextContent('J006')
  })

  it('opens a cited source in the help center', async () => {
    const { user, panel } = await openAssistant()
    await user.click(within(panel).getByRole('button', { name: 'What does idle wait mean?' }))
    const cite = fixtures.askDocs.citations[0]
    await user.click(await within(panel).findByRole('button', { name: new RegExp(`^${cite.title}`) }))
    const help = await screen.findByRole('dialog', { name: 'Help' })
    expect(await within(help).findByRole('heading', { level: 2, name: cite.title })).toBeInTheDocument()
  })

  it('says plainly when it does not know, and offers other questions', async () => {
    const { user, panel } = await openAssistant()
    await user.type(within(panel).getByRole('textbox', { name: 'Your question' }), 'Tell me a joke{Enter}')
    expect(await within(panel).findByText(/^I don't know that one/)).toBeInTheDocument()
    expect(within(within(panel).getByLabelText('Suggested questions')).getAllByRole('button').length).toBeGreaterThan(0)
  })

  it('shows an error in the conversation when the service fails', async () => {
    const { user, panel } = await openAssistant('dispatcher', {
      ...workspaceRoutes(), 'POST /assistant/ask': json(503, errorBody('unavailable', 'Assistant is busy, try again')),
    })
    await user.type(within(panel).getByRole('textbox', { name: 'Your question' }), 'hello{Enter}')
    expect(await within(panel).findByText('Assistant is busy, try again')).toBeInTheDocument()
  })

  it('keeps the conversation when closed and reopened, and can clear it', async () => {
    const { user, panel } = await openAssistant()
    await user.type(within(panel).getByRole('textbox', { name: 'Your question' }), 'Tell me a joke{Enter}')
    await within(panel).findByText(/^I don't know/)
    await user.click(within(panel).getByRole('button', { name: 'Close assistant' }))
    await user.click(screen.getByRole('button', { name: 'Ask the assistant' }))
    const again = await screen.findByRole('dialog', { name: 'Assistant' })
    expect(within(again).getByText('Tell me a joke')).toBeInTheDocument()
    await user.click(within(again).getByRole('button', { name: 'Clear' }))
    expect(within(again).queryByText('Tell me a joke')).not.toBeInTheDocument()
  })
})

describe('keyboard shortcuts', () => {
  it('switches views with 1–6, but not while typing', async () => {
    const { user } = await signInAs('dispatcher')
    await user.keyboard('2')
    expect(screen.getByRole('tab', { name: /Floor plan/ })).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('6')
    expect(screen.getByRole('tab', { name: /Benchmark/ })).toHaveAttribute('aria-selected', 'true')
    const seed = screen.getByRole('spinbutton', { name: 'Seed' })
    seed.focus()
    fireEvent.keyDown(seed, { key: '1' })
    expect(screen.getByRole('tab', { name: /Benchmark/ })).toHaveAttribute('aria-selected', 'true')
  })
})
