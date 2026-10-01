// Phone layout (Pixel 7 viewport, touch): drawer controls and no sideways scrolling.
import { expect, test } from './fixtures.js'

// Compare with the device's screen, not innerWidth: on phones the layout viewport grows to fit
// overflowing content, so innerWidth would hide exactly the bug this checks for.
const noSidewaysScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth <= screen.width + 1)

test('controls live in a drawer that opens and closes', async ({ page, signIn }) => {
  await signIn()
  const generate = page.getByRole('button', { name: 'Generate shift' })
  await expect(generate).not.toBeInViewport()
  await page.getByRole('button', { name: 'Open controls' }).tap()
  await expect(generate).toBeInViewport()
  await generate.tap()
  await expect(generate).not.toBeInViewport()
  await expect(page.getByRole('region', { name: 'Recommendation' })).toBeVisible()
})

test('every view fits the screen width', async ({ page, signIn }) => {
  await signIn()
  for (const tab of ['Overview', 'Floor plan', 'Schedule', 'Workforce', 'Live dispatch', 'Benchmark']) {
    await page.getByRole('tab', { name: new RegExp(tab) }).tap()
    await expect(page.getByRole('tab', { name: new RegExp(tab) })).toHaveAttribute('aria-selected', 'true')
    expect(await noSidewaysScroll(page), `${tab} scrolls sideways`).toBe(true)
  }
})

test('a job can be inspected by touch', async ({ page, signIn }) => {
  await signIn()
  await page.getByRole('tab', { name: /Floor plan/ }).tap()
  const job = page.getByRole('button', { name: /^J\d{3},/ }).first()
  const id = (await job.getAttribute('aria-label')).split(',')[0]
  await job.tap()
  await expect(page.getByRole('complementary', { name: 'Inspector' }).getByRole('heading', { level: 3 })).toContainText(id)
})

test('the top bar fits, and theme and sign-out stay reachable from the user menu', async ({ page, signIn }) => {
  await signIn()
  const bar = page.getByRole('banner')
  expect(await bar.evaluate((el) => el.scrollWidth <= el.clientWidth + 1), 'top bar overflows').toBe(true)
  const avatar = page.getByRole('button', { name: 'D', exact: true })
  await expect(avatar).toBeInViewport({ ratio: 1 })
  await avatar.tap()
  const menu = page.getByRole('menu')
  await menu.getByRole('button', { name: 'Dark' }).tap()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await menu.getByRole('menuitem', { name: 'Sign out' }).tap()
  await expect(page.getByRole('button', { name: 'Continue as Dispatcher' })).toBeVisible()
})

test('the assistant fills the phone screen and answers', async ({ page, signIn }) => {
  await signIn()
  await page.getByRole('button', { name: 'Ask the assistant' }).tap()
  const panel = page.getByRole('dialog', { name: 'Assistant' })
  const box = await panel.boundingBox()
  expect(box.width).toBeGreaterThanOrEqual(page.viewportSize().width - 1)
  await panel.getByRole('button', { name: 'Which jobs are unassigned?' }).tap()
  await expect(panel.getByRole('list', { name: 'Conversation' }).getByText(/unassigned|serves every job/).first()).toBeVisible()
  await panel.getByRole('button', { name: 'Close assistant' }).tap()
  await expect(panel).toHaveCount(0)
})
