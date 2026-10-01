// WCAG 2.1 A/AA checks (axe-core) on every main screen: no serious or critical violations.
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from './fixtures.js'

async function audit(page, include) {
  let builder = new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
  if (include) builder = builder.include(include)
  const { violations } = await builder.analyze()
  const serious = violations.filter((v) => ['serious', 'critical'].includes(v.impact))
  expect(serious.map((v) => `${v.id} (${v.impact}): ${v.help} → ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([])
}

test('sign-in', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await audit(page)
})

for (const tab of ['Overview', 'Floor plan', 'Schedule', 'Workforce', 'Live dispatch', 'Benchmark']) {
  test(`${tab} view`, async ({ page, signIn }) => {
    await signIn()
    await page.getByRole('tab', { name: new RegExp(tab) }).click()
    await expect(page.getByRole('tab', { name: new RegExp(tab) })).toHaveAttribute('aria-selected', 'true')
    await page.waitForTimeout(300)
    await audit(page)
  })
}

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
