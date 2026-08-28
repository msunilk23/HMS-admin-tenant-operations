import { test, expect, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const doctor = {
  username: 'e2e_doctor_task7',
  password: 'E2eDoctor@123',
  visitId: '0d608e02-7583-50a6-a153-d4a45deb866c',
}

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

function resetFixture() {
  execFileSync(process.env.PYTHON ?? 'python', [
    path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'),
    'reset_prescription_scenario',
  ], {
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
  await page.getByPlaceholder(/you@hospital\.in or mkrish66/i).fill(doctor.username)
  await page.locator('input[type="password"]').fill(doctor.password)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page).toHaveURL(/doctor/)
}

async function openPrescription(page: Page) {
  await login(page)
  await page.goto(`/doctor/prescription/${doctor.visitId}`)
  await page.getByRole('button', { name: /add medicine/i }).click()
  await expect(page.getByPlaceholder(/search formulary generic, brand or composition/i).first()).toBeVisible()
}

test.describe.serial('P25 pharmacy prescription integration', () => {
  test.beforeEach(() => resetFixture())

  test('searches by generic and brand through the active formulary', async ({ page }) => {
    await openPrescription(page)
    const search = page.getByPlaceholder(/search formulary generic, brand or composition/i).first()
    await search.fill('E2E Paracetamol')
    await expect(page.getByRole('button', { name: /E2E Paracetamol.*500.*Tablet/i })).toBeVisible()
    await search.fill('E2E Dolo')
    await expect(page.getByRole('button', { name: /E2E Paracetamol.*500.*Tablet/i })).toBeVisible()
  })

  test('selects a formulary product and calculates UNIT quantity', async ({ page }) => {
    await openPrescription(page)
    const search = page.getByPlaceholder(/search formulary generic, brand or composition/i).first()
    await search.fill('E2E Dolo')
    await page.getByRole('button', { name: /E2E Paracetamol.*500.*Tablet/i }).click()
    await page.getByPlaceholder(/e\.g\. 500mg/i).first().fill('1')
    const saveResponse = page.waitForResponse(response => response.url().includes('/api/v1/prescriptions') && response.request().method() === 'POST')
    await page.getByRole('button', { name: /save prescription/i }).click()
    const response = await saveResponse
    expect(response.ok(), await response.text()).toBeTruthy()
    const body = await response.json()
    expect(body.items[0].auto_quantity).toBe('10')
    expect(body.items[0].final_quantity).toBe('10')
  })

  test('requires and persists a quantity override reason', async ({ page }) => {
    await openPrescription(page)
    const search = page.getByPlaceholder(/search formulary generic, brand or composition/i).first()
    await search.fill('E2E Dolo')
    await page.getByRole('button', { name: /E2E Paracetamol.*500.*Tablet/i }).click()
    await page.getByPlaceholder(/e\.g\. 500mg/i).first().fill('1')
    await page.getByPlaceholder(/e\.g\. 10/i).first().fill('12')
    await page.getByPlaceholder(/reason if overriding calculated quantity/i).first().fill('Patient supplied pack size')
    const saveResponse = page.waitForResponse(response => response.url().includes('/api/v1/prescriptions') && response.request().method() === 'POST')
    await page.getByRole('button', { name: /save prescription/i }).click()
    const response = await saveResponse
    expect(response.ok(), await response.text()).toBeTruthy()
    const body = await response.json()
    expect(body.items[0].auto_quantity).toBe('10')
    expect(body.items[0].final_quantity).toBe('12')
    expect(body.items[0].quantity_override_flag).toBe(true)
    expect(body.items[0].quantity_override_reason).toBe('Patient supplied pack size')
  })

  test('supports explicit free-text medicine with a reason and reloads it', async ({ page }) => {
    await openPrescription(page)
    await page.getByRole('checkbox', { name: /free-text medicine exception/i }).check()
    await page.getByPlaceholder(/reason required for free-text medicine/i).fill('No suitable formulary alternative')
    await page.getByPlaceholder(/search formulary generic, brand or composition/i).first().fill('External medicine')
    await page.getByPlaceholder(/e\.g\. 500mg/i).first().fill('1')
    await page.getByPlaceholder(/e\.g\. 10/i).first().fill('1')
    const saveResponse = page.waitForResponse(response => response.url().includes('/api/v1/prescriptions') && response.request().method() === 'POST')
    await page.getByRole('button', { name: /save prescription/i }).click()
    const response = await saveResponse
    expect(response.ok(), await response.text()).toBeTruthy()
    await page.goto(`/doctor/prescription/${doctor.visitId}`)
    await expect(page.getByPlaceholder(/reason required for free-text medicine/i)).toHaveValue('No suitable formulary alternative')
  })
})
