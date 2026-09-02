import { expect, test, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createPageDiagnostics, type PageDiagnosticsCollector } from './support/pageDiagnostics'

const admin = { username: 'e2e_admin_task7', password: 'E2eAdmin@123' }
const nurse = { username: 'e2e_nurse_task7', password: 'E2eNurse@123' }
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

test.setTimeout(120_000)

function seedRosterContext() {
  execFileSync(process.env.E2E_PYTHON ?? process.env.PYTHON ?? 'python', [path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'), 'seed_ra4_scenario'], {
    cwd: path.join(repoRoot, 'backend'),
    stdio: 'inherit',
    env: {
      ...process.env,
      E2E_ENVIRONMENT: 'E2E',
      E2E_ALLOW_DESTRUCTIVE_RESET: 'true',
      DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital',
      SECRET_KEY: process.env.SECRET_KEY ?? 'test-secret-key',
    },
  })
}

async function login(page: Page, user: typeof admin) {
  await page.goto('/login')
  await page.getByPlaceholder(/you@hospital\.in or mkrish66/i).fill(user.username)
  await page.locator('input[type="password"]').fill(user.password)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page).not.toHaveURL(/login/)
}

async function relogin(page: Page, user: typeof admin) {
  await page.context().clearCookies()
  await page.evaluate(() => localStorage.clear())
  await login(page, user)
}

test.describe.serial('Release A Nurse Roster real-role workflow', () => {
  let diagnostics: PageDiagnosticsCollector

  test.beforeEach(() => seedRosterContext())
  test.beforeEach(async ({ page }) => { diagnostics = createPageDiagnostics(page) })
  test.afterEach(async ({ page: _page }, info) => { await diagnostics.flush(info) })

  test('admin creates and records attendance while Nurse receives read-only own roster', async ({ page }) => {
    await login(page, admin)
    await page.goto('/admin/nurse-roster')
    await expect(page.getByRole('heading', { name: 'Nurse Roster' })).toBeVisible()
    await page.getByRole('button', { name: 'New Roster Entry' }).click()
    const rosterForm = page.getByRole('heading', { name: 'New Roster Entry' }).locator('..')
    await rosterForm.getByRole('combobox').first().selectOption({ label: 'E2E Nurse A' })
    await page.getByLabel('Department').selectOption({ label: 'E2E General Medicine' })
    await page.getByLabel('Room').fill('RA-5 Ward')
    const create = page.waitForResponse(response => response.url().endsWith('/api/v1/nurse-roster') && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Save' }).click()
    expect((await create).status()).toBe(201)
    await expect(page.getByRole('status')).toContainText('Roster entry created')
    await expect(page.getByText('E2E Nurse A')).toBeVisible()
    await expect(page.getByText(/RA-5 Ward/)).toBeVisible()

    const attendance = page.waitForResponse(response => response.url().includes('/api/v1/nurse-roster/') && response.request().method() === 'PATCH')
    await page.getByRole('button', { name: 'Mark present' }).click()
    expect((await attendance).ok()).toBeTruthy()
    await expect(page.getByRole('button', { name: 'Present' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Edit' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Deactivate' })).toBeVisible()

    await relogin(page, nurse)
    await page.goto('/nurse/roster')
    await expect(page.getByRole('heading', { name: 'My Roster' })).toBeVisible()
    await expect(page.getByText(/E2E General Medicine.*Morning/)).toBeVisible()
    await expect(page.getByText(/RA-5 Ward/)).toBeVisible()
    await expect(page.getByText('Present', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: /New Roster Entry|Edit|Deactivate/ })).toHaveCount(0)
  })
})
