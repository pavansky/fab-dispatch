// Shared Playwright fixtures: every test fails on a browser console error or uncaught
// exception, and `signIn` opens the workspace with a demo role.
import { test as base, expect } from '@playwright/test'

export const test = base.extend({
  // The first-run tour is tested on its own (tour.spec.js); everywhere else it's already been seen.
  page: async ({ page }, use) => {
    await page.addInitScript(() => { try { localStorage.setItem('fab-dispatch-tour', 'done') } catch { /* ignore */ } })
    await use(page)
  },

  consoleErrors: [async ({ page }, use) => {
    const errors = []
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
    page.on('pageerror', (e) => errors.push(e.message))
    await use(errors)
    expect(errors, 'browser console errors').toEqual([])
  }, { auto: true }],

  signIn: async ({ page }, use) => {
    await use(async (role = 'dispatcher', query = '') => {
      await page.goto(`/?as=${role}${query ? `&${query}` : ''}`)
      await expect(page.getByRole('tablist', { name: 'Views' })).toBeVisible()
      await expect(page.getByText('5 strategies solved')).toBeAttached() // hidden on phones, still announced
    })
  },
})

export { expect }

/** Click an empty spot inside a tool area on the floor plan (where a job can be reported). */
export async function clickToolArea(page, index = 0) {
  const point = await page.evaluate((i) => {
    const svg = document.querySelector('svg.floor')
    const area = svg.querySelectorAll('rect.f-area')[i].getBBox()
    const taken = [...svg.querySelectorAll('.f-job .mark, .f-eng rect')].map((el) => {
      const b = el.getBBox()
      return { x: b.x + b.width / 2, y: b.y + b.height / 2 }
    })
    // Scan the area for the spot farthest from any job or engineer, away from the label.
    let best = null
    for (let x = area.x + 8; x < area.x + area.width - 8; x += 4) {
      for (let y = area.y + 22; y < area.y + area.height - 8; y += 4) {
        const d = Math.min(...taken.map((t) => Math.hypot(t.x - x, t.y - y)), Infinity)
        if (!best || d > best.d) best = { x, y, d }
      }
    }
    const p = new DOMPoint(best.x, best.y).matrixTransform(svg.getScreenCTM())
    return { x: p.x, y: p.y }
  }, index)
  await page.mouse.click(point.x, point.y)
}
