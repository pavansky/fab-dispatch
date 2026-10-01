// Planning against the real backend: sign-in, comparison, explanations, what-ifs, benchmark.
import { clickToolArea, expect, test } from './fixtures.js'

test('signs in with a demo role and compares five strategies', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await page.getByRole('button', { name: 'Continue as Dispatcher' }).click()

  const reco = page.getByRole('region', { name: 'Recommendation' })
  await expect(reco).toBeVisible()
  await expect(page.getByRole('button', { name: 'View on floor plan' })).toHaveCount(5)
  await expect(page.getByText('5 strategies solved')).toBeVisible()
  await expect(reco.getByRole('heading', { level: 2 })).not.toBeEmpty()
  await expect(page.locator('.card.score.recommended')).toHaveCount(1)
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
})

test('re-plans every strategy when a cost weight moves', async ({ page, signIn }) => {
  await signIn()
  const replans = []
  page.on('request', (r) => { if (r.url().endsWith('/api/plan') && r.method() === 'POST') replans.push(r.postDataJSON()) })
  await page.getByRole('slider', { name: 'Walking' }).fill('10')
  await expect.poll(() => replans.length).toBe(5)
  expect(replans.every((b) => b.weights.travel_100m === 10)).toBe(true)
  await expect(page.getByText('5 strategies solved')).toBeVisible()
})

test('explains how each strategy handled a job on the floor plan', async ({ page, signIn }) => {
  await signIn()
  await page.getByRole('tab', { name: /Floor plan/ }).click()
  const job = page.getByRole('button', { name: /^J\d{3},/ }).first()
  const id = (await job.getAttribute('aria-label')).split(',')[0]
  await job.click()
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  await expect(inspector.getByRole('heading', { level: 3 })).toContainText(id)
  await expect(inspector.locator('.decision')).toHaveCount(5)
  await expect(page).toHaveURL(new RegExp(`job=${id}`))
})

test('reports a new tool-down by tapping the floor', async ({ page, signIn }) => {
  await signIn()
  await page.getByText('Report a job by tapping the floor').click()
  await expect(page.getByRole('tab', { name: /Floor plan/ })).toHaveAttribute('aria-selected', 'true')
  await clickToolArea(page, 1)
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  await expect(inspector.getByRole('heading', { level: 3 })).toContainText('J046') // 45 jobs + 1
  await expect(inspector.locator('.decision')).toHaveCount(5)
})

test('opens a shared deep link with the job selected', async ({ page, signIn }) => {
  await signIn('dispatcher', 'tab=floor&job=J006')
  await expect(page.getByRole('tab', { name: /Floor plan/ })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('complementary', { name: 'Inspector' }).getByRole('heading', { level: 3 })).toContainText('J006')
})

test('runs the benchmark and the optimality gap', async ({ page, signIn }) => {
  test.setTimeout(120_000)
  await signIn()
  await page.getByRole('spinbutton', { name: 'Engineers' }).fill('5')
  await page.getByRole('spinbutton', { name: 'Jobs' }).fill('12')
  await page.getByRole('tab', { name: /Benchmark/ }).click()
  await page.getByRole('combobox', { name: 'Seeds per preset' }).selectOption('5')
  await page.getByRole('button', { name: 'Run benchmark' }).click()
  await expect(page.getByRole('button', { name: 'Re-run benchmark' })).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText(/^Best value:/)).toHaveCount(4)
  await expect(page.getByRole('table').first()).toContainText('PyVRP')

  await page.getByRole('button', { name: 'Measure gaps' }).click()
  await expect(page.getByText(/0% = optimal/)).toBeVisible({ timeout: 60_000 })
})
