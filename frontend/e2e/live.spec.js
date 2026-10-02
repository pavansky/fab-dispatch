// Live dispatch across two browsers: the dispatcher drives, a viewer watches over SSE.
import { clickToolArea, expect, test } from './fixtures.js'

const clockOf = (page) => page.locator('.live-clock strong')

async function startShift(page) {
  await page.getByRole('tab', { name: /Live dispatch/ }).click()
  await page.getByRole('button', { name: 'Start live shift' }).click()
  await expect(page.getByRole('region', { name: 'Dispatch log' })).toBeVisible()
  await expect(page.getByText('live', { exact: true })).toBeVisible()
  return new URL(page.url()).searchParams.get('shift')
}

test('a dispatcher drives the clock and the plan re-optimises', async ({ page, signIn }) => {
  await signIn()
  const id = await startShift(page)
  expect(id).toMatch(/^fab1-300mm-logic\.[0-9a-f]{12}$/) // ids carry their fab, which routes to its database
  await expect(clockOf(page)).toHaveText('07:00')
  await page.getByRole('button', { name: '+1 h' }).click()
  await expect(clockOf(page)).toHaveText('08:00')
  await expect(page.getByText('Clock driven by')).toContainText('you')
  await expect(page.getByRole('region', { name: 'Dispatch log' }).locator('li.ev')).not.toHaveCount(0)
})

test('a reported bottleneck down is re-planned and announced', async ({ page, signIn }) => {
  await signIn()
  await startShift(page)
  await page.getByText('Tap floor to report a bottleneck down').click()
  await clickToolArea(page, 0)
  await expect(page.getByText(/^Bottleneck down:/)).toBeVisible()
  await expect(page.getByRole('region', { name: 'Dispatch log' }).locator('li.ev-job_reported').first()).toBeVisible()
})

test('a viewer in another browser sees changes stream in, read-only', async ({ page, signIn, browser }) => {
  await signIn()
  const id = await startShift(page)

  const other = await browser.newContext()
  const viewer = await other.newPage()
  await viewer.goto(`/?as=viewer&shift=${id}`)
  await expect(viewer.getByText('Viewing only')).toBeVisible()
  await expect(viewer.getByRole('button', { name: '+1 h' })).toHaveCount(0)
  await expect(clockOf(viewer)).toHaveText('07:00')

  await page.getByRole('button', { name: '+1 h' }).click()
  await expect(clockOf(viewer)).toHaveText('08:00') // pushed over Server-Sent Events
  await expect(viewer.getByText(/Clock driven by/)).toContainText('dispatcher@demo.local')
  await other.close()
})

test('a shift can be left and rejoined from recent shifts', async ({ page, signIn }) => {
  await signIn()
  const id = await startShift(page)
  await page.getByRole('button', { name: 'Leave' }).click()
  const row = page.getByRole('row').filter({ hasText: id })
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: 'Join' }).click()
  await expect(page.getByRole('region', { name: 'Dispatch log' })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`shift=${id}`))
})
