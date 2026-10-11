// WCAG 2.1 A/AA checks (axe-core) on every main screen, in both themes and on the phone
// project too: no moderate, serious or critical violations.
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from './fixtures.js'

async function audit(page, include) {
  let builder = new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
  if (include) builder = builder.include(include)
  const { violations } = await builder.analyze()
  const counted = violations.filter((v) => ['moderate', 'serious', 'critical'].includes(v.impact))
  expect(counted.map((v) => `${v.id} (${v.impact}): ${v.help} → ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([])
}

// What to wait for before auditing a view, instead of a fixed delay.
const READY = {
  Overview: (page) => page.getByRole('region', { name: 'Recommendation' }),
  'Floor plan': (page) => page.getByRole('group', { name: /^Fab floor plan/ }),
  Schedule: (page) => page.getByRole('table', { name: /^Shift schedule/ }),
  Workforce: (page) => page.getByRole('heading', { name: 'Demand vs certified supply' }),
  'Live dispatch': (page) => page.getByRole('button', { name: 'Start live shift' }),
  Benchmark: (page) => page.getByRole('button', { name: 'Run benchmark' }),
}

async function openView(page, tab) {
  await page.getByRole('tab', { name: new RegExp(tab) }).click()
  await expect(page.getByRole('tab', { name: new RegExp(tab) })).toHaveAttribute('aria-selected', 'true')
  await expect(READY[tab](page)).toBeVisible()
}

/** Switch to the dark theme from the user menu (the only theme control present at every width). */
async function useDarkTheme(page) {
  await page.getByRole('button', { name: 'D', exact: true }).click()
  await page.getByRole('menu').getByRole('button', { name: 'Dark' }).click()
  await page.keyboard.press('Escape')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
}

test('sign-in', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await audit(page)
})

for (const tab of Object.keys(READY)) {
  test(`${tab} view`, async ({ page, signIn }) => {
    await signIn()
    await openView(page, tab)
    await audit(page)
  })
}

test('dark theme', async ({ page, signIn }) => {
  await signIn()
  await useDarkTheme(page)
  await audit(page)
  await openView(page, 'Schedule') // the Gantt bars carry text on colour
  await audit(page)
  await openView(page, 'Floor plan')
  await audit(page)
})

test('help center, assistant and about panels', async ({ page, signIn }) => {
  await signIn()
  await page.keyboard.press('?')
  await expect(page.getByRole('dialog', { name: 'Help' }).getByText('Get started').first()).toBeVisible()
  await audit(page, '.help-panel')
  await page.keyboard.press('Escape')
  await page.keyboard.press('/')
  await page.getByRole('dialog', { name: 'Assistant' }).getByRole('textbox').fill('How do I report a bug?')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: 'Assistant' }).getByLabel('Rate this answer')).toBeVisible()
  await audit(page, '.assistant')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'D', exact: true }).click()
  await page.getByRole('menuitem', { name: 'About & support' }).click()
  await expect(page.getByRole('dialog', { name: 'About and support' }).getByRole('status')).toContainText('operational')
  await audit(page, '.about')
})
