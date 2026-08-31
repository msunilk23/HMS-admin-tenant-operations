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

function seedP34() {
  execFileSync(process.env.PYTHON ?? 'python', [path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'), 'seed_p34_scenario'], { cwd: path.join(repoRoot, 'backend'), stdio: 'inherit', env })
}
function snapshotP34() {
  return JSON.parse(execFileSync(process.env.PYTHON ?? 'python', [path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'), 'snapshot_p34'], { cwd: path.join(repoRoot, 'backend'), encoding: 'utf8', env }))
}
async function login(page: Page, user: typeof pharmacist) {
  await page.goto('/login')
  await page.getByPlaceholder(/you@hospital/i).fill(user.username)
  await page.locator('input[type=password]').fill(user.password)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page).not.toHaveURL(/login/)
}

async function openDashboard(page: Page, user = pharmacist) {
  await login(page, user)
  const response = page.waitForResponse(item => item.url().endsWith('/api/v1/pharmacy-dashboard') && item.request().method() === 'GET')
  await page.goto('/pharmacy/dashboard')
  expect((await response).ok()).toBeTruthy()
  await expect(page.getByRole('heading', { name: 'Pharmacy Dashboard' })).toBeVisible()
}

test.describe.serial('P34 Pharmacy dashboard and reports', () => {
  let diagnostics: PageDiagnosticsCollector
  test.beforeEach(() => seedP34())
  test.beforeEach(async ({ page }) => { diagnostics = createPageDiagnostics(page) })
  test.afterEach(async ({ page: _page }, info) => diagnostics.flush(info))

  test('shows a separate operational dashboard and drills into a report', async ({ page }) => {
    await openDashboard(page)
    await expect(page).toHaveURL(/\/pharmacy\/dashboard$/)
    await expect(page.getByText('Prescriptions pending')).toBeVisible()
    await expect(page.getByText('Operational view. Financial totals and valuation require additional reporting access.')).toBeVisible()
    await expect(page.getByText("Today's Pharmacy sales")).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'Command Center' })).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Pharmacy Dashboard' })).toBeVisible()

    await page.getByText('Low-stock items').click()
    await expect(page.getByLabel('Pharmacy report')).toHaveValue('reorder')
    await page.getByLabel('Pharmacy report').selectOption('current-stock')
    await expect(page.getByText('P28-EARLY', { exact: true })).toBeVisible()
  })

  test('acknowledges a scoped alert exactly once', async ({ page }) => {
    await openDashboard(page)
    await page.getByRole('button', { name: 'Alerts' }).click()
    await expect(page.getByText('Low stock: P28-EARLY')).toBeVisible()
    await page.getByLabel('Acknowledgement note for Low stock: P28-EARLY').fill('Stock replenishment request reviewed')
    const response = page.waitForResponse(item => item.url().includes('/pharmacy-dashboard/alerts/') && item.url().endsWith('/acknowledge') && item.request().method() === 'POST')
    await page.getByRole('button', { name: 'Acknowledge' }).click()
    expect((await response).ok()).toBeTruthy()
    await expect(page.getByText('No alerts match this status.')).toBeVisible()
    const snapshot = snapshotP34()
    expect(snapshot.alerts).toEqual([{ id: '7e693508-1ad4-56db-8d7e-d79f8191c848', status: 'ACKNOWLEDGED' }])
    expect(snapshot.acknowledgements).toHaveLength(1)
    expect(snapshot.acknowledgements[0].note).toBe('Stock replenishment request reviewed')
    expect(snapshot.operation_count).toBe(1)
  })

  test('exports a report and versions alert configuration as admin', async ({ page }) => {
    await openDashboard(page, admin)
    await expect(page.getByText("Today's Pharmacy sales")).toBeVisible()
    await page.getByRole('button', { name: 'Reports' }).click()
    const downloadPromise = page.waitForEvent('download')
    const exportResponse = page.waitForResponse(item => item.url().includes('/pharmacy-dashboard/reports/current-stock/export'))
    await page.getByRole('button', { name: 'Export CSV' }).click()
    expect((await exportResponse).ok()).toBeTruthy()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toBe('pharmacy-current-stock.csv')

    await page.getByRole('button', { name: 'Configuration' }).click()
    await page.getByLabel('Expiry horizon days').fill('120')
    const update = page.waitForResponse(item => item.url().endsWith('/pharmacy-dashboard/alert-configuration') && item.request().method() === 'PUT')
    await page.getByRole('button', { name: 'Save configuration' }).click()
    expect((await update).ok()).toBeTruthy()
    const snapshot = snapshotP34()
    expect(snapshot.configurations).toEqual([expect.objectContaining({ scope_key: 'facility:016e30e1-d9b4-555f-b538-7ce7747376a3', expiry_horizon_days: 120, version: 1 })])
    expect(snapshot.operation_count).toBe(1)
  })

  test('denies a user without Pharmacy dashboard permission', async ({ page, request }) => {
    await login(page, unauthorized)
    await page.goto('/pharmacy/dashboard')
    await expect(page).not.toHaveURL(/pharmacy\/dashboard/)
    await expect(page.getByRole('link', { name: 'Pharmacy Dashboard' })).toHaveCount(0)
    const loginResponse = await request.post('/api/v1/auth/login', { data: { login_id: unauthorized.username, password: unauthorized.password } })
    const token = (await loginResponse.json()).access_token
    const forbidden = await request.get('/api/v1/pharmacy-dashboard', { headers: { Authorization: `Bearer ${token}` } })
    expect(forbidden.status()).toBe(403)
    expect(snapshotP34().operation_count).toBe(0)
  })
})
