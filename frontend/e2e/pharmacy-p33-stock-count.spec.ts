import { expect, test, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createPageDiagnostics, type PageDiagnosticsCollector } from './support/pageDiagnostics'

const pharmacist = { username: 'e2e_pharmacist_task7', password: 'E2ePharmacist@123' }
const manager = { username: 'e2e_store_manager_task7', password: 'E2eManager@123' }
const recounter = { username: 'e2e_recounter_task7', password: 'E2eRecounter@123' }
const unauthorized = { username: 'e2e_receptionist_task7', password: 'E2eReception@123' }
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const env = { ...process.env, E2E_ENVIRONMENT: 'E2E', E2E_ALLOW_DESTRUCTIVE_RESET: 'true', DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital', SECRET_KEY: process.env.SECRET_KEY ?? 'test-secret-key' }

function seedP33() {
  execFileSync(process.env.PYTHON ?? 'python', [path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'), 'seed_p33_scenario'], { cwd: path.join(repoRoot, 'backend'), stdio: 'inherit', env })
}

function snapshotP33() {
  return JSON.parse(execFileSync(process.env.PYTHON ?? 'python', [path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'), 'snapshot_p33'], { cwd: path.join(repoRoot, 'backend'), encoding: 'utf8', env }))
}

async function login(page: Page, user: typeof pharmacist) {
  await page.goto('/login')
  await page.getByPlaceholder(/you@hospital/i).fill(user.username)
  await page.locator('input[type=password]').fill(user.password)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page).not.toHaveURL(/login/)
}

async function relogin(page: Page, user: typeof pharmacist) {
  await page.evaluate(() => localStorage.clear())
  await login(page, user)
  await page.goto('/pharmacy/inventory-counts')
  await expect(page.getByRole('heading', { name: 'Inventory Counts' })).toBeVisible()
}

async function createAndSubmitCount(page: Page) {
  await login(page, pharmacist)
  await page.goto('/pharmacy/inventory-counts')
  await expect(page.getByRole('heading', { name: 'Inventory Counts' })).toBeVisible()
  await page.getByLabel('Pharmacy location').selectOption({ label: 'P33 Count Pharmacy' })
  await page.getByRole('button', { name: 'PARTIAL' }).click()
  await page.getByLabel(/P33-COUNT/).check()
  const created = page.waitForResponse(response => response.url().endsWith('/pharmacy/inventory-counts') && response.request().method() === 'POST')
  await page.getByRole('button', { name: 'Create count' }).click()
  expect((await created).status()).toBe(201)
  const started = page.waitForResponse(response => response.url().endsWith('/start') && response.request().method() === 'POST')
  await page.getByRole('button', { name: 'Start counting' }).click()
  expect((await started).ok()).toBeTruthy()
  const frozen = snapshotP33().batches.find((batch: { batch_number: string }) => batch.batch_number === 'P33-COUNT')
  expect(frozen.frozen_by_count_id).not.toBeNull()
  await page.getByLabel('Physical quantity P33-COUNT').fill('18')
  await page.getByLabel('Variance reason P33-COUNT').fill('Cycle count shortage confirmed')
  let recordRequests = 0
  page.on('request', request => { if (request.url().includes('/details/') && request.method() === 'PATCH') recordRequests += 1 })
  const recorded = page.waitForResponse(response => response.url().includes('/pharmacy/inventory-counts/') && response.url().includes('/details/') && response.request().method() === 'PATCH')
  await page.getByRole('button', { name: 'Save' }).dblclick()
  expect((await recorded).ok()).toBeTruthy()
  expect(recordRequests).toBe(1)
  await expect(page.getByRole('button', { name: 'Submit count' })).toBeEnabled()
  const submitted = page.waitForResponse(response => response.url().endsWith('/submit') && response.request().method() === 'POST')
  await page.getByRole('button', { name: 'Submit count' }).click()
  expect((await submitted).ok()).toBeTruthy()
  await expect(page.getByText('SUBMITTED', { exact: true }).last()).toBeVisible()
}

test.describe.serial('P33 stock count and variance adjustment', () => {
  let diagnostics: PageDiagnosticsCollector
  test.beforeEach(() => seedP33())
  test.beforeEach(async ({ page }) => { diagnostics = createPageDiagnostics(page) })
  test.afterEach(async ({ page: _page }, info) => diagnostics.flush(info))

  test('counts, approves, and explicitly applies a signed variance', async ({ page }) => {
    await createAndSubmitCount(page)
    await relogin(page, manager)
    await page.locator('section').filter({ has: page.getByRole('heading', { name: 'Count register' }) }).getByRole('button').first().click()
    await page.getByLabel('Decision reason').fill('Independent manager verification complete')
    const approved = page.waitForResponse(response => response.url().endsWith('/approve') && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Approve count' }).click()
    expect((await approved).ok()).toBeTruthy()
    await expect(page.getByRole('button', { name: 'Review adjustment application' })).toBeVisible()
    expect(snapshotP33().ledger).toEqual([])
    await page.getByRole('button', { name: 'Review adjustment application' }).click()
    await expect(page.getByText(/release the inventory freeze/)).toBeVisible()
    const applied = page.waitForResponse(response => response.url().endsWith('/apply') && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Apply adjustments' }).click()
    expect((await applied).ok()).toBeTruthy()
    await expect(page.getByText('APPLIED', { exact: true }).last()).toBeVisible()

    const snapshot = snapshotP33()
    expect(snapshot.counts).toHaveLength(1)
    expect(snapshot.counts[0].status).toBe('APPLIED')
    expect(snapshot.counts[0].variance_quantity).toBe('-2.000')
    expect(snapshot.counts[0].approved_by).toBe(snapshot.ids.manager)
    expect(snapshot.counts[0].applied_by).toBe(snapshot.ids.manager)
    expect(snapshot.batches.find((batch: { batch_number: string }) => batch.batch_number === 'P33-COUNT')).toMatchObject({ available_quantity: '18.000', frozen_by_count_id: null })
    expect(snapshot.ledger.map((entry: { transaction_type: string; quantity: string }) => [entry.transaction_type, entry.quantity])).toEqual([['ADJUSTMENT_OUT', '-2.000']])
    expect(snapshot.operation_count).toBeGreaterThanOrEqual(6)
    expect(snapshot.audit_count).toBeGreaterThanOrEqual(5)
  })

  test('denies the inventory-count route to a role without P33 permissions', async ({ page }) => {
    await login(page, unauthorized)
    await page.goto('/pharmacy/inventory-counts')
    await expect(page).not.toHaveURL(/pharmacy\/inventory-counts/)
    expect(snapshotP33().counts).toEqual([])
  })

  test('assigns and resubmits a recount without replacing the original observation', async ({ page }) => {
    await createAndSubmitCount(page)
    await relogin(page, manager)
    await page.locator('section').filter({ has: page.getByRole('heading', { name: 'Count register' }) }).getByRole('button').first().click()
    await page.getByLabel('Decision reason').fill('Independent recount required')
    await page.getByLabel('Recount assignee user ID').fill(snapshotP33().ids.recounter)
    const requested = page.waitForResponse(response => response.url().endsWith('/recounts') && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Request recount' }).click()
    expect((await requested).ok()).toBeTruthy()
    await relogin(page, recounter)
    await page.locator('section').filter({ has: page.getByRole('heading', { name: 'Count register' }) }).getByRole('button').first().click()
    const started = page.waitForResponse(response => response.url().endsWith('/recounts/start') && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Start recount' }).click()
    expect((await started).ok()).toBeTruthy()
    await page.getByLabel('Physical quantity P33-COUNT').fill('19')
    await page.getByLabel('Variance reason P33-COUNT').fill('Recount confirmed one unit shortage')
    const recorded = page.waitForResponse(response => response.url().includes('/recounts/details/') && response.request().method() === 'PATCH')
    await page.getByRole('button', { name: 'Save recount' }).click()
    expect((await recorded).ok()).toBeTruthy()
    const resubmitted = page.waitForResponse(response => response.url().endsWith('/recounts/resubmit') && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Resubmit recount' }).click()
    expect((await resubmitted).ok()).toBeTruthy()
    const snapshot = snapshotP33()
    expect(snapshot.counts[0]).toMatchObject({ status: 'RESUBMITTED', physical_total_quantity: '19.000', variance_quantity: '-1.000' })
    expect(snapshot.details[0]).toMatchObject({ physical_quantity: '18.000', variance_quantity: '-2.000' })
    expect(snapshot.recounts[0]).toMatchObject({ status: 'SUBMITTED', assigned_to: snapshot.ids.recounter, physical_quantity: '19.000', variance_quantity: '-1.000', counted_by: snapshot.ids.recounter })
  })
})
