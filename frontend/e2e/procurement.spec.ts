import { test, expect, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const admin = {
  username: 'e2e_admin_task7',
  password: 'E2eAdmin@123',
}

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

function resetFixture() {
  execFileSync(process.env.PYTHON ?? 'python', [
    path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'),
    'seed',
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
  await page.getByPlaceholder(/you@hospital\.in or mkrish66/i).fill(admin.username)
  await page.locator('input[type="password"]').fill(admin.password)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page).toHaveURL(/dashboard/)
}

test.describe('P26.14 procurement workflows', () => {
  test.beforeEach(() => resetFixture())

  test('hospital admin can view the seeded purchase order and create a GRN batch receipt', async ({ page }) => {
    await login(page)
    await page.goto('/admin/pharmacy/purchase-orders')
    await expect(page.getByRole('heading', { name: 'Purchase Orders' })).toBeVisible()
    await expect(page.getByText('E2E-PO-0001')).toBeVisible()
    await expect(page.getByText('SENT', { exact: true }).first()).toBeVisible()

    await page.goto('/admin/pharmacy/goods-receipts')
    await expect(page.getByRole('heading', { name: 'Goods Receipts' })).toBeVisible()
    await page.getByLabel(/sent purchase order/i).selectOption({ label: 'E2E-PO-0001 · SENT' })
    await page.getByRole('button', { name: /create draft grn/i }).click()
    await expect(page.getByRole('heading', { name: 'Add received batch' })).toBeVisible()

    await page.getByRole('combobox', { name: /select po item/i }).selectOption({ label: /E2E-DOLO-500/ })
    await page.getByPlaceholder(/received qty/i).fill('10')
    await page.getByPlaceholder(/free qty/i).fill('0')
    await page.getByPlaceholder(/batch number/i).fill('E2E-BATCH-001')
    await page.getByLabel(/expires/i).fill('2027-12-31')
    const receiveResponse = page.waitForResponse(response => response.url().includes('/api/v1/pharmacy/grn/') && response.url().endsWith('/items') && response.request().method() === 'POST')
    await page.getByRole('button', { name: /record batch/i }).click()
    const received = await receiveResponse
    expect(received.ok(), await received.text()).toBeTruthy()
    await expect(page.getByText(/E2E-BATCH-001.*2027-12-31/)).toBeVisible()

    const finalizeResponse = page.waitForResponse(response => response.url().includes('/api/v1/pharmacy/grn/') && response.url().endsWith('/finalize') && response.request().method() === 'POST')
    await page.getByRole('button', { name: /^finalize$/i }).click()
    const finalized = await finalizeResponse
    expect(finalized.ok(), await finalized.text()).toBeTruthy()
  })

  test('expired batches are rejected by the receiving API', async ({ page }) => {
    await login(page)
    await page.goto('/admin/pharmacy/goods-receipts')
    await page.getByLabel(/sent purchase order/i).selectOption({ label: 'E2E-PO-0001 · SENT' })
    await page.getByRole('button', { name: /create draft grn/i }).click()
    await page.getByRole('combobox', { name: /select po item/i }).selectOption({ label: /E2E-DOLO-500/ })
    await page.getByPlaceholder(/received qty/i).fill('1')
    await page.getByPlaceholder(/batch number/i).fill('E2E-EXPIRED-001')
    await page.getByLabel(/expires/i).fill('2020-01-01')
    const responsePromise = page.waitForResponse(response => response.url().includes('/api/v1/pharmacy/grn/') && response.url().endsWith('/items') && response.request().method() === 'POST')
    await page.getByRole('button', { name: /record batch/i }).click()
    const response = await responsePromise
    expect(response.status()).toBe(422)
  })
})
