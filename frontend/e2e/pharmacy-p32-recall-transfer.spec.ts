import { expect, test, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createPageDiagnostics, type PageDiagnosticsCollector } from './support/pageDiagnostics'

const pharmacist = { username: 'e2e_pharmacist_task7', password: 'E2ePharmacist@123' }
const admin = { username: 'e2e_admin_task7', password: 'E2eAdmin@123' }
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const env = { ...process.env, E2E_ENVIRONMENT: 'E2E', E2E_ALLOW_DESTRUCTIVE_RESET: 'true', DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital', SECRET_KEY: process.env.SECRET_KEY ?? 'test-secret-key' }
function seedP32() { execFileSync(process.env.PYTHON ?? 'python', [path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'), 'seed_p32_scenario'], { cwd: path.join(repoRoot, 'backend'), stdio: 'inherit', env }) }
function snapshotP32() { return JSON.parse(execFileSync(process.env.PYTHON ?? 'python', [path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'), 'snapshot_p32'], { cwd: path.join(repoRoot, 'backend'), encoding: 'utf8', env })) }
async function login(page: Page, user: typeof pharmacist) { await page.goto('/login'); await page.getByPlaceholder(/you@hospital/i).fill(user.username); await page.locator('input[type=password]').fill(user.password); await page.getByRole('button', { name: /sign in/i }).click(); await expect(page).not.toHaveURL(/login/) }
async function relogin(page: Page, user: typeof pharmacist) { await page.evaluate(() => localStorage.clear()); await login(page, user); await page.goto('/pharmacy/operations'); await expect(page.getByRole('heading', { name: 'Recall & Stock Transfer' })).toBeVisible() }
async function createRecall(page: Page) {
  const ids = snapshotP32().ids
  await page.getByLabel('Medicine ID').fill(ids.medicine)
  await page.getByLabel('Batch number').fill('P30-SINGLE-BATCH')
  await page.getByLabel('Recall reason').fill('Confirmed quality defect from manufacturer investigation')
  await page.getByLabel('Regulatory reference').fill('CDSCO-P32-E2E')
  const response = page.waitForResponse((item) => item.url().endsWith('/pharmacy/recalls') && item.request().method() === 'POST')
  await page.getByRole('button', { name: 'Create recall' }).click()
  expect((await response).status()).toBe(201)
  await expect(page.getByRole('status')).toContainText('created')
}
async function selectTransfer(page: Page, quantity: string) {
  await page.getByRole('tab', { name: 'Stock transfers' }).click()
  await page.getByLabel('Source location').selectOption({ label: 'P32 Central Store' })
  await page.getByLabel('Destination location').selectOption({ label: 'P32 Emergency Pharmacy' })
  const batchValue = await page.getByLabel('Eligible batch').locator('option').filter({ hasText: 'P32-TRANSFER' }).getAttribute('value')
  await page.getByLabel('Eligible batch').selectOption(batchValue || '')
  await page.getByLabel('Transfer quantity').fill(quantity)
}

test.describe.serial('P32 recall and stock transfer', () => {
  let diagnostics: PageDiagnosticsCollector
  test.beforeEach(() => seedP32())
  test.beforeEach(async ({ page }) => { diagnostics = createPageDiagnostics(page) })
  test.afterEach(async ({ page: _page }, info) => diagnostics.flush(info))

  test('approves a batch recall, quarantines stock, and identifies affected patients', async ({ page }) => {
    await login(page, pharmacist); await page.goto('/pharmacy/operations'); await createRecall(page)
    await relogin(page, admin)
    await page.getByText('P30-SINGLE-BATCH', { exact: false }).first().click()
    const approval = page.waitForResponse((item) => item.url().includes('/pharmacy/recalls/') && item.url().endsWith('/approve') && item.request().method() === 'POST')
    await page.getByRole('button', { name: 'Approve recall' }).click(); expect((await approval).ok()).toBeTruthy()
    await expect(page.getByRole('status')).toContainText('approved')
    await expect(page.getByText('P30 Single')).toBeVisible(); await expect(page.getByText('E2E-P30-SINGLE')).toBeVisible()
    const snapshot = snapshotP32(); const batch = snapshot.batches.find((item: { batch_number: string }) => item.batch_number === 'P30-SINGLE-BATCH')
    expect(batch.available_quantity).toBe('0.000'); expect(batch.status).toBe('RECALLED'); expect(snapshot.recalls[0].status).toBe('ACTIVE')
    expect(snapshot.ledger.map((item: { transaction_type: string; quantity: string }) => [item.transaction_type, item.quantity])).toContainEqual(['RECALL_QUARANTINE', '-5.000'])
    await relogin(page, pharmacist); await page.getByRole('tab', { name: 'Stock transfers' }).click(); await page.getByLabel('Source location').selectOption({ label: 'P32 Central Store' })
    await expect(page.getByLabel('Eligible batch').locator('option').filter({ hasText: 'P30-SINGLE-BATCH' })).toHaveCount(0)
  })

  test('approves, dispatches, and receives an exact inter-location transfer', async ({ page }) => {
    await login(page, pharmacist); await page.goto('/pharmacy/operations'); await selectTransfer(page, '6')
    const creation = page.waitForResponse((item) => item.url().endsWith('/pharmacy/transfers') && item.request().method() === 'POST')
    await page.getByRole('button', { name: 'Create draft' }).click(); expect((await creation).status()).toBe(201)
    await relogin(page, admin); await page.getByRole('tab', { name: 'Stock transfers' }).click()
    await page.locator('section').filter({ hasText: 'Transfers and in-transit stock' }).getByRole('button').first().click()
    const approval = page.waitForResponse((item) => item.url().endsWith('/approve') && item.request().method() === 'POST'); await page.getByRole('button', { name: 'Approve transfer' }).click(); expect((await approval).ok()).toBeTruthy()
    const dispatch = page.waitForResponse((item) => item.url().endsWith('/dispatch') && item.request().method() === 'POST'); await page.getByRole('button', { name: 'Dispatch transfer' }).click(); expect((await dispatch).ok()).toBeTruthy()
    await page.getByLabel('Quantity received').fill('6')
    const receipt = page.waitForResponse((item) => item.url().endsWith('/receive') && item.request().method() === 'POST'); await page.getByRole('button', { name: 'Receive stock' }).click(); expect((await receipt).ok()).toBeTruthy()
    await expect(page.getByText('Destination stock received: 6')).toBeVisible()
    const snapshot = snapshotP32(); const transfer = snapshot.transfers[0]
    expect(transfer.status).toBe('RECEIVED'); expect(transfer.received_quantity).toBe('6.000')
    const source = snapshot.batches.find((item: { batch_number: string; pharmacy_location_id: string }) => item.batch_number === 'P32-TRANSFER' && item.pharmacy_location_id === snapshot.ids.source)
    const destination = snapshot.batches.find((item: { batch_number: string; pharmacy_location_id: string }) => item.batch_number === 'P32-TRANSFER' && item.pharmacy_location_id === snapshot.ids.destination)
    expect(source.available_quantity).toBe('14.000'); expect(source.reserved_quantity).toBe('0.000'); expect(destination.available_quantity).toBe('6.000')
  })

  test('blocks self approval and excess quantity without mutation', async ({ page }) => {
    await login(page, admin); await page.goto('/pharmacy/operations'); await createRecall(page)
    await expect(page.getByText(/different authorized manager/)).toBeVisible(); await expect(page.getByRole('button', { name: 'Approve recall' })).toHaveCount(0)
    await relogin(page, pharmacist); await page.getByRole('tab', { name: 'Stock transfers' }).click(); await page.getByLabel('Source location').selectOption({ label: 'P32 Central Store' })
    await page.getByLabel('Destination location').selectOption({ label: 'P32 Emergency Pharmacy' }); const batchValue = await page.getByLabel('Eligible batch').locator('option').filter({ hasText: 'P32-TRANSFER' }).getAttribute('value'); await page.getByLabel('Eligible batch').selectOption(batchValue || ''); await page.getByLabel('Transfer quantity').fill('21'); await page.getByRole('button', { name: 'Create draft' }).click()
    await expect(page.getByRole('alert')).toContainText('exceeds available')
    const snapshot = snapshotP32(); expect(snapshot.transfers).toEqual([]); expect(snapshot.batches.find((item: { batch_number: string }) => item.batch_number === 'P32-TRANSFER').available_quantity).toBe('20.000')
  })
})