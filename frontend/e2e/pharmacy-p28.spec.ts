import { test, expect, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createPageDiagnostics, type PageDiagnosticsCollector } from './support/pageDiagnostics'

const pharmacist = { username: 'e2e_pharmacist_task7', password: 'E2ePharmacist@123' }
const facilityId = '016e30e1-d9b4-555f-b538-7ce7747376a3'
const locationId = '9cb201ea-b1b8-5857-8f7a-764967d21f17'
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

function seedP28() {
  execFileSync(process.env.PYTHON ?? 'python', [path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'), 'seed_p28_scenario'], {
    cwd: path.join(repoRoot, 'backend'),
    stdio: 'inherit',
    env: {
      ...process.env,
      DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital',
      SECRET_KEY: process.env.SECRET_KEY ?? 'test-secret-key',
    },
  })
}

async function login(page: Page) {
  await page.goto('/login')
  await page.getByPlaceholder(/you@hospital\.in or mkrish66/i).fill(pharmacist.username)
  await page.locator('input[type="password"]').fill(pharmacist.password)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page).toHaveURL(/pharmacy/)
}

test.describe.serial('P28 pharmacy dispensing workflow', () => {
  let diagnostics: PageDiagnosticsCollector

  test.beforeEach(() => seedP28())

  test.beforeEach(async ({ page }) => {
    diagnostics = createPageDiagnostics(page)
  })

  test.afterEach(async ({ page: _page }, testInfo) => {
    await diagnostics.flush(testInfo)
  })

  test('completes FEFO reservation and confirmed dispensing', async ({ page }) => {
    await login(page)
    await page.goto('/pharmacy')
    await expect(page.getByText('E2E Patient', { exact: true })).toBeVisible()
    await expect(page.getByText('E2E Dolo', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Dispense' }).click()
    await page.getByLabel('Facility ID').fill(facilityId)
    await page.getByLabel('Pharmacy location ID').fill(locationId)
    await page.getByRole('button', { name: 'Start review' }).click()
    await expect(page.getByRole('button', { name: /validate and reserve fefo stock/i })).toBeVisible()
    await page.getByRole('button', { name: /validate and reserve fefo stock/i }).click()
    await expect(page.getByText(/ready for billing/i)).toBeVisible()
    await page.getByRole('button', { name: 'Confirm dispense' }).click()
    await expect(page.getByText(/stock and ledger updated/i)).toBeVisible()

    await page.reload()
    await expect(page.getByText(/dispensed orders today/i)).toBeVisible()

    const snapshot = JSON.parse(execFileSync(process.env.PYTHON ?? 'python', [path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'), 'snapshot'], {
      cwd: path.join(repoRoot, 'backend'),
      encoding: 'utf8',
      env: {
        ...process.env,
        DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital',
        SECRET_KEY: process.env.SECRET_KEY ?? 'test-secret-key',
      },
    }))
    expect(snapshot.state.p28.status).toBe('CONFIRMED')
    expect(snapshot.state.p28.item.prescribed_quantity).toBe('10.000')
    expect(snapshot.state.p28.item.internal_confirmed_quantity).toBe('10.000')
    expect(snapshot.state.p28.item.outside_purchase_quantity).toBe('0.000')
    expect(snapshot.state.p28.allocations.map((row: { batch_number: string; confirmed_dispensed_quantity: string }) => [row.batch_number, row.confirmed_dispensed_quantity])).toEqual([
      ['P28-EARLY', '6.000'],
      ['P28-LATER', '4.000'],
    ])
    expect(snapshot.state.p28.allocations.every((row: { status: string; available_quantity: string; reserved_quantity: string }) => row.status === 'CONSUMED' && row.reserved_quantity === '0.000')).toBeTruthy()
    expect(snapshot.state.p28.allocations.map((row: { batch_number: string; available_quantity: string }) => [row.batch_number, row.available_quantity])).toEqual([
      ['P28-EARLY', '0.000'],
      ['P28-LATER', '16.000'],
    ])
    expect(snapshot.state.p28.ledger_quantities).toEqual(['-6.000', '-4.000'])
    expect(snapshot.state.p28.ledger_quantities.length).toBe(2)
  })
})