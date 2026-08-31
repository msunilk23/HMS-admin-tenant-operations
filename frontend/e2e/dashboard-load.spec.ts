import { test, expect, type APIRequestContext, type Page } from '@playwright/test'
import { createPageDiagnostics, type PageDiagnosticsCollector } from './support/pageDiagnostics'

const admin = {
  username: 'e2e_admin_task7',
  password: 'E2eAdmin@123',
}

const receptionist = {
  username: 'e2e_receptionist_task7',
  password: 'E2eReception@123',
}

async function loginAs(request: APIRequestContext, credentials = admin) {
  const response = await request.post('/api/v1/auth/login', {
    data: { login_id: credentials.username, password: credentials.password },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return { Authorization: `Bearer ${(await response.json()).access_token}` }
}

async function login(page: Page) {
  await page.goto('/login')
  await page.getByPlaceholder(/you@hospital\.in or mkrish66/i).fill(admin.username)
  await page.locator('input[type="password"]').fill(admin.password)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page).toHaveURL(/dashboard/)
}

test.describe('P25.19 Dashboard Load', () => {
  let diagnostics: PageDiagnosticsCollector

  test.beforeEach(async ({ page }) => {
    diagnostics = createPageDiagnostics(page)
  })

  test.afterEach(async ({ page: _page }, testInfo) => {
    await diagnostics.flush(testInfo)
  })

  test('general dashboard keeps its route, cards, permissions, and loading contract', async ({ page, request }) => {
    const statsResponse = page.waitForResponse(response => response.url().endsWith('/api/v1/admin/stats'))
    await login(page)
    await expect(page).toHaveURL(/\/dashboard$/)
    expect((await statsResponse).ok()).toBeTruthy()
    await expect(page.getByRole('heading', { name: 'Command Center' })).toBeVisible()
    await expect(page.getByText('Total Patients', { exact: true })).toBeVisible()
    await expect(page.getByText('OPD Visits Today', { exact: true })).toBeVisible()
    await expect(page.getByText('Total Staff', { exact: true })).toBeVisible()
    await expect(page.getByText('Revenue Today', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('Pharmacy', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('Could not load dashboard data.', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'Pharmacy Dashboard' })).toHaveCount(0)

    const receptionistHeaders = await loginAs(request, receptionist)
    const forbidden = await request.get('/api/v1/admin/stats', { headers: receptionistHeaders })
    expect(forbidden.status()).toBe(403)
  })

  test('admin stats endpoint returns the dashboard contract', async ({ request }) => {
    const headers = await loginAs(request)
    const response = await request.get('/api/v1/admin/stats', { headers })
    expect(response.ok(), await response.text()).toBeTruthy()
    const data = await response.json()
    expect(data).toHaveProperty('total_patients')
    expect(data).toHaveProperty('visits_today')
    expect(data).toHaveProperty('revenue_today')
    expect(data).toHaveProperty('departments')
    expect(Array.isArray(data.departments)).toBe(true)
  })
})
