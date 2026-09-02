import { test, expect, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createPageDiagnostics, type PageDiagnosticsCollector } from './support/pageDiagnostics'

const pharmacist = { username: 'e2e_pharmacist_task7', password: 'E2ePharmacist@123' }
const checker = { username: 'e2e_retail_checker_task7', password: 'E2eRetailChecker@123' }
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

test.setTimeout(120_000)

function backendCommand(command: string, encoding?: BufferEncoding): string {
  return execFileSync(process.env.E2E_PYTHON ?? process.env.PYTHON ?? 'python', [path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'), command], {
    cwd: path.join(repoRoot, 'backend'),
    encoding,
    stdio: encoding ? undefined : 'inherit',
    env: {
      ...process.env,
      E2E_ENVIRONMENT: 'E2E',
      E2E_ALLOW_DESTRUCTIVE_RESET: 'true',
      DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital',
      SECRET_KEY: process.env.SECRET_KEY ?? 'test-secret-key',
    },
  }) as string
}

async function login(page: Page, credentials = pharmacist) {
  await page.goto('/login')
  await page.getByPlaceholder(/you@hospital\.in or mkrish66/i).fill(credentials.username)
  await page.locator('input[type="password"]').fill(credentials.password)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page).toHaveURL(/pharmacy/)
}

async function openRetail(page: Page) {
  await page.goto('/pharmacy/otc')
  await expect(page.getByRole('heading', { name: 'Retail Dispensing' })).toBeVisible()
  await page.getByLabel('Retail pharmacy location').selectOption({ label: 'RA4 Retail Counter (RA4-RETAIL)' })
}

async function relogin(page: Page, credentials: typeof checker) {
  await page.context().clearCookies()
  await page.evaluate(() => localStorage.clear())
  await login(page, credentials)
}

test.describe.serial('RA-4 retail pharmacy workflow', () => {
  let diagnostics: PageDiagnosticsCollector

  test.beforeEach(() => backendCommand('seed_ra4_scenario'))
  test.beforeEach(async ({ page }) => { diagnostics = createPageDiagnostics(page) })
  test.afterEach(async ({ page: _page }, testInfo) => { await diagnostics.flush(testInfo) })

  test('dispenses an OTC cash sale with invoice, payment, stock, and ledger evidence', async ({ page }) => {
    await login(page)
    await openRetail(page)
    await page.getByLabel('Search retail medicines').fill('E2E Dolo')
    await page.getByRole('button', { name: 'Add E2E Dolo' }).click()
    await page.getByRole('spinbutton', { name: 'E2E Dolo quantity', exact: true }).fill('2')
    await page.getByRole('button', { name: 'Review payment' }).click()
    await page.getByRole('button', { name: 'Capture payment and dispense' }).click()
    await expect(page.getByRole('status')).toContainText('Payment captured and stock dispensed')
    await expect(page.getByRole('status')).toContainText('OTC')

    const snapshot = JSON.parse(backendCommand('snapshot_ra4', 'utf8'))
    expect(snapshot.sales).toEqual([expect.objectContaining({ classification: 'OTC', status: 'FULLY_DISPENSED', controlled_sale: false, payment_status: 'PAID' })])
    expect(snapshot.invoices).toEqual([expect.objectContaining({ classification: 'OTC', status: 'PAID', total: '25.20' })])
    expect(snapshot.payments).toEqual([expect.objectContaining({ status: 'CAPTURED', amount: '25.20', payment_method: 'CASH' })])
    expect(snapshot.batches).toContainEqual({ batch_number: 'RA4-OTC-FEFO', available_quantity: '18.000' })
    expect(snapshot.ledger).toContainEqual({ transaction_type: 'RETAIL_DISPENSE', quantity: '-2.000' })
  })

  test('enforces controlled-sale maker-checker across pharmacist sessions', async ({ page }) => {
    await login(page)
    await openRetail(page)
    await page.getByRole('button', { name: 'External prescription' }).click()
    await page.getByLabel('Search retail medicines').fill('RA4 Controlled')
    await page.getByRole('button', { name: 'Add RA4 Controlled Medicine' }).click()
    const fields: Record<string, string> = {
      'Patient name': 'RA4 Browser Patient',
      'Patient age': '35',
      'Patient gender': 'female',
      'Patient mobile': '9000000044',
      'Patient address': '44 Release Street',
      'Prescriber name': 'Dr External',
      'Registration number': 'RA4-REG-44',
      'Issuing facility / clinic': 'Release Clinic',
      'Prescription reference': 'RA4-RX-44',
      'Prescription document reference': 'document://ra4-browser-rx',
      'Registered patient ID': '982cf4f6-e6f8-58e5-95f6-eb213821d4a3',
      'Government ID type': 'Passport',
      'Government ID last four': '0044',
    }
    for (const [label, value] of Object.entries(fields)) await page.getByLabel(label).fill(value)
    await page.getByRole('spinbutton', { name: 'RA4 Controlled Medicine duration days', exact: true }).fill('2')

    const createResponsePromise = page.waitForResponse(response => response.url().includes('/pharmacy/retail/sales') && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Submit for verification' }).click()
    const created = await (await createResponsePromise).json() as { id: string }
    await page.getByRole('button', { name: 'Verify original prescription' }).click()
    await expect(page.getByText(/different authorized Pharmacist/)).toBeVisible()

    await relogin(page, checker)
    await page.goto('/pharmacy/otc')
    await page.getByLabel('Retail sale ID').fill(created.id)
    await page.getByRole('button', { name: 'Resume' }).click()
    await expect(page.getByText(/different authorized Pharmacist/)).toBeVisible()
    await page.getByRole('button', { name: 'Capture payment and dispense' }).click()
    await expect(page.getByRole('status')).toContainText('EXTERNAL PRESCRIPTION')

    const snapshot = JSON.parse(backendCommand('snapshot_ra4', 'utf8'))
    expect(snapshot.sales).toEqual([expect.objectContaining({
      classification: 'EXTERNAL_PRESCRIPTION',
      status: 'FULLY_DISPENSED',
      controlled_sale: true,
    })])
    expect(snapshot.sales[0].verified_by).toBeTruthy()
    expect(snapshot.sales[0].dispensed_by).toBeTruthy()
    expect(snapshot.sales[0].dispensed_by).not.toBe(snapshot.sales[0].verified_by)
    expect(snapshot.invoices[0]).toEqual(expect.objectContaining({ classification: 'EXTERNAL_PRESCRIPTION', status: 'PAID' }))
    expect(snapshot.payments[0]).toEqual(expect.objectContaining({ status: 'CAPTURED', payment_method: 'CASH' }))
    expect(snapshot.batches).toContainEqual({ batch_number: 'RA4-CTRL-FEFO', available_quantity: '9.000' })
  })
})
