import { expect, test, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createPageDiagnostics, type PageDiagnosticsCollector } from './support/pageDiagnostics'

const pharmacist = { username: 'e2e_pharmacist_task7', password: 'E2ePharmacist@123' }
const admin = { username: 'e2e_admin_task7', password: 'E2eAdmin@123' }
const unauthorized = { username: 'e2e_receptionist_task7', password: 'E2eReception@123' }
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const env = { ...process.env, E2E_ENVIRONMENT: 'E2E', E2E_ALLOW_DESTRUCTIVE_RESET: 'true', DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital', SECRET_KEY: process.env.SECRET_KEY ?? 'test-secret-key' }
function seedP31() { execFileSync(process.env.PYTHON ?? 'python', [path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'), 'seed_p31_scenario'], { cwd: path.join(repoRoot, 'backend'), stdio: 'inherit', env }) }
function snapshotP31() { return JSON.parse(execFileSync(process.env.PYTHON ?? 'python', [path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'), 'snapshot_p31'], { cwd: path.join(repoRoot, 'backend'), encoding: 'utf8', env })) }
async function login(page: Page, user: typeof pharmacist) { await page.goto('/login'); await page.getByPlaceholder(/you@hospital/i).fill(user.username); await page.locator('input[type=password]').fill(user.password); await page.getByRole('button', { name: /sign in/i }).click(); await expect(page).not.toHaveURL(/login/) }
async function relogin(page: Page, user: typeof pharmacist) { await page.evaluate(() => localStorage.clear()); await login(page, user); await page.goto('/pharmacy/quarantine'); await expect(page.getByRole('heading', { name: 'Stock Quarantine' })).toBeVisible() }
async function createQuarantine(page: Page, batchLabel: string, quantity: string, reason: 'INVESTIGATION' | 'EXPIRED' | 'DAMAGED') {
  const batchValue = await page.getByLabel('Batch and location').locator('option').filter({ hasText: batchLabel }).getAttribute('value')
  await page.getByLabel('Batch and location').selectOption(batchValue || '')
  await page.getByLabel('Quarantine quantity').fill(quantity)
  await page.getByLabel('Quarantine reason').selectOption(reason)
  await page.getByLabel('Quarantine notes').fill(`P31 ${reason.toLowerCase()} browser evidence`)
  const response = page.waitForResponse((item) => item.url().endsWith('/pharmacy/quarantines') && item.request().method() === 'POST')
  await page.getByRole('button', { name: 'Quarantine stock' }).click()
  expect((await response).status()).toBe(201)
  await expect(page.getByRole('status')).toContainText('quarantined')
}

test.describe.serial('P31 stock quarantine', () => {
  let diagnostics: PageDiagnosticsCollector
  test.beforeEach(() => seedP31())
  test.beforeEach(async ({ page }) => { diagnostics = createPageDiagnostics(page) })
  test.afterEach(async ({ page: _page }, info) => diagnostics.flush(info))

  test('quarantines and releases investigative stock with reconciled ledger', async ({ page }) => {
    await login(page, pharmacist); await page.goto('/pharmacy/quarantine')
    await createQuarantine(page, 'P31-INVESTIGATIVE', '3', 'INVESTIGATION')
    let snapshot = snapshotP31()
    expect(snapshot.batches.find((item: { batch_number: string }) => item.batch_number === 'P31-INVESTIGATIVE').available_quantity).toBe('7.000')
    expect(snapshot.quarantines[0].remaining_quantity).toBe('3.000')
    expect(snapshot.ledger.map((item: { transaction_type: string; quantity: string }) => [item.transaction_type, item.quantity])).toEqual([['QUARANTINE_OUT', '-3.000']])
    await relogin(page, admin)
    await page.getByLabel('Release evidence').fill('Investigation completed and packaging verified intact')
    const release = page.waitForResponse((item) => item.url().includes('/release') && item.request().method() === 'POST')
    await page.getByRole('button', { name: 'Release stock' }).click(); expect((await release).ok()).toBeTruthy()
    snapshot = snapshotP31()
    expect(snapshot.batches.find((item: { batch_number: string }) => item.batch_number === 'P31-INVESTIGATIVE').available_quantity).toBe('10.000')
    expect(snapshot.quarantines[0].remaining_quantity).toBe('0.000')
    expect(snapshot.ledger.map((item: { transaction_type: string; quantity: string }) => [item.transaction_type, item.quantity])).toEqual([['QUARANTINE_OUT', '-3.000'], ['QUARANTINE_RELEASE', '3.000']])
  })

  test('disposes expired stock with witness and one physical disposal movement', async ({ page }) => {
    await login(page, pharmacist); await page.goto('/pharmacy/quarantine')
    await createQuarantine(page, 'P31-EXPIRED', '2', 'EXPIRED')
    await relogin(page, admin)
    await expect(page.getByRole('button', { name: 'Release stock' })).toHaveCount(0)
    const actors = snapshotP31().actors
    await page.getByLabel('Disposal reason').fill('Expired stock confirmed unsafe for patient use')
    await page.getByLabel('Disposal method').fill('Licensed biomedical waste')
    await page.getByLabel('Witness user ID').fill(actors.witness)
    const disposal = page.waitForResponse((item) => item.url().includes('/dispose') && item.request().method() === 'POST')
    await page.getByRole('button', { name: 'Dispose stock' }).click(); expect((await disposal).ok()).toBeTruthy()
    const snapshot = snapshotP31(); const quarantine = snapshot.quarantines[0]
    expect(quarantine.status).toBe('DISPOSED'); expect(quarantine.remaining_quantity).toBe('0.000'); expect(quarantine.witnessed_by).toBe(actors.witness); expect(quarantine.disposal_method).toBe('Licensed biomedical waste')
    expect(snapshot.batches.find((item: { batch_number: string }) => item.batch_number === 'P31-EXPIRED').available_quantity).toBe('6.000')
    expect(snapshot.ledger.filter((item: { transaction_type: string }) => item.transaction_type === 'QUARANTINE_DISPOSAL')).toHaveLength(1)
    expect(snapshot.ledger.find((item: { transaction_type: string }) => item.transaction_type === 'QUARANTINE_DISPOSAL').quantity).toBe('-2.000')
  })

  test('blocks excess quantity, self approval, and unauthorized route access', async ({ page }) => {
    await login(page, pharmacist); await page.goto('/pharmacy/quarantine')
    const damagedValue = await page.getByLabel('Batch and location').locator('option').filter({ hasText: 'P31-DAMAGED' }).getAttribute('value'); await page.getByLabel('Batch and location').selectOption(damagedValue || ''); await page.getByLabel('Quarantine quantity').fill('7'); await page.getByLabel('Quarantine reason').selectOption('DAMAGED'); await page.getByRole('button', { name: 'Quarantine stock' }).click(); await expect(page.getByRole('alert')).toContainText('exceeds available')
    expect(snapshotP31().ledger).toEqual([])
    await relogin(page, admin); await createQuarantine(page, 'P31-DAMAGED', '1', 'DAMAGED')
    await expect(page.getByText(/different manager or administrator/)).toBeVisible(); await expect(page.getByRole('button', { name: 'Dispose stock' })).toHaveCount(0)
    await page.evaluate(() => localStorage.clear()); await login(page, unauthorized); await page.goto('/pharmacy/quarantine'); await expect(page).not.toHaveURL(/pharmacy\/quarantine/)
  })
})