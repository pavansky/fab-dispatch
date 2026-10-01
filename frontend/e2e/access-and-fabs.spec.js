// Roles, fab switching, theme and sign-out against the real backend.
import { expect, test } from './fixtures.js'

test('a viewer can explore but not run benchmarks or start shifts', async ({ page, signIn }) => {
  await signIn('viewer')
  await page.getByRole('tab', { name: /Benchmark/ }).click()
  await expect(page.getByRole('button', { name: 'Run benchmark' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Measure gaps' })).toBeDisabled()
  await page.getByRole('tab', { name: /Live dispatch/ }).click()
  await expect(page.getByRole('button', { name: 'Start live shift' })).toBeDisabled()
})

test('the API refuses dispatcher actions from a viewer, whatever the UI shows', async ({ page, signIn }) => {
  await signIn('viewer')
  const token = await page.evaluate(() => localStorage.getItem('fab-dispatch-demo-token'))
  const res = await page.request.post('/api/benchmark', { headers: { Authorization: `Bearer ${token}` }, data: { seeds: 1 } })
  expect(res.status()).toBe(403)
  expect((await res.json()).error.code).toBeTruthy()
})

test('switching fab loads that site’s floor, families and presets', async ({ page, signIn }) => {
  await signIn()
  await page.getByRole('combobox', { name: 'Fab' }).selectOption('fab2-200mm-analog')
  await expect(page).toHaveURL(/fab=fab2-200mm-analog/)
  await expect(page.getByRole('combobox', { name: 'Preset' }).getByRole('option', { name: 'Photo crunch' })).toBeAttached()
  await expect(page.getByRole('button', { name: 'View on floor plan' })).toHaveCount(5)
  await page.getByRole('tab', { name: /Floor plan/ }).click()
  await expect(page.locator('svg.floor').getByText('PHOTOLITHOGRAPHY')).toBeVisible()
  await expect(page.locator('svg.floor').getByText('LITHOGRAPHY', { exact: true })).toHaveCount(0)
})

test('keeps the chosen theme across reloads, light by default', async ({ page, signIn }) => {
  await signIn()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await page.getByRole('button', { name: 'Dark' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
})

test('signs out back to the sign-in screen', async ({ page, signIn }) => {
  await signIn()
  await page.getByRole('button', { name: 'D', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Sign out' }).click()
  await expect(page.getByRole('button', { name: 'Continue as Dispatcher' })).toBeVisible()
})
