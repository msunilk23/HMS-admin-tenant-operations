import { test, expect, type APIRequestContext, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const fixtureScript = path.join(repoRoot, 'backend', 'tests', 'e2e_seed_nurse_vitals.py')

type Fixture = {
  schema: string
  tenant_id: string
  nurse_user_id: string
  doctor_user_id: string
  nurse_username: string
  doctor_username: string
  nurse_password: string
  doctor_password: string
  department_id: string
  doctor_id: string
  patient_id: string
  visit_id: string
}

let fixture: Fixture

function fixtureEnv() {
  return {
    ...process.env,
    DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital',
    SECRET_KEY: process.env.SECRET_KEY ?? 'test-secret-key',
    REDIS_URL: process.env.REDIS_URL ?? 'redis://localhost:6379',
    PYTHONPATH: path.join(repoRoot, 'backend'),
  }
}

function runFixture(command: 'seed' | 'cleanup', input?: string): string {
  return execFileSync(process.env.PYTHON ?? 'python', [fixtureScript, command], {
    cwd: path.join(repoRoot, 'backend'),
    env: fixtureEnv(),
    input,
    stdio: ['pipe', 'pipe', 'pipe'],
  }).toString('utf8').trim()
}

async function login(page: Page, username: string, password: string, expectedPath: RegExp) {
  await page.goto('/login')
  await page.getByPlaceholder(/you@hospital\.in or mkrish66/i).fill(username)
  await page.locator('input[type="password"]').fill(password)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page).toHaveURL(expectedPath)
}

async function authHeaders(request: APIRequestContext, username: string, password: string) {
  const response = await request.post('/api/v1/auth/login', { data: { login_id: username, password } })
  expect(response.ok()).toBeTruthy()
  return { Authorization: `Bearer ${(await response.json()).access_token}` }
}

async function fillPartialDraft(page: Page) {
  await page.locator('input[name="bp_systolic"]').fill('120')
  await page.locator('input[name="bp_diastolic"]').fill('80')
  await page.locator('input[name="temperature"]').fill('98.6')
  await page.locator('input[name="pulse"]').fill('72')
}

async function fillCompleteVitals(page: Page) {
  await page.locator('input[name="spo2"]').fill('98')
  await page.locator('input[name="respiratory_rate"]').fill('18')
  await page.locator('input[name="weight"]').fill('70')
  await page.locator('input[name="height"]').fill('170')
  await page.locator('input[name="pain_score"]').fill('2')
  await page.locator('input[name="blood_glucose"]').fill('96')
  await page.locator('textarea[name="chief_complaint"]').fill('Fever and cough for two days')
  await page.locator('input[name="known_no_allergies"]').check()
  await page.locator('select[name="general_condition"]').selectOption('Stable')
  await page.locator('select[name="level_of_consciousness"]').selectOption('Alert')
  await page.locator('textarea[name="nurse_notes"]').fill('Patient stable during pre-vitals')
}

test.describe.serial('Nurse vitals draft and handoff', () => {
  test.beforeAll(() => {
    fixture = JSON.parse(runFixture('seed')) as Fixture
  })

  test.afterAll(() => {
    if (fixture) runFixture('cleanup', JSON.stringify(fixture))
  })

  test('saves a partial draft with status draft and restores it', async ({ page, request }) => {
    await login(page, fixture.nurse_username, fixture.nurse_password, /nurse\/vitals/)
    await expect(page.getByText('Nurse Vitals Patient')).toBeVisible()
    await page.getByText('Nurse Vitals Patient').click()
    await fillPartialDraft(page)

    const draftRequest = page.waitForRequest(requestItem => requestItem.url().includes('/api/v1/vitals') && requestItem.method() === 'POST')
    const draftResponse = page.waitForResponse(response => response.url().includes('/api/v1/vitals') && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Save Draft', exact: true }).click()
    const requestBody = JSON.parse((await draftRequest).postData() ?? '{}') as { status?: string; temperature?: number }
    expect(requestBody.status).toBe('draft')
    expect(requestBody.temperature).toBe(37)
    expect((await draftResponse).ok()).toBeTruthy()

    await expect(page.getByText('Draft saved successfully.')).toBeVisible()
    await expect(page.getByText(/Cannot send to doctor|Please fill in all mandatory/i)).not.toBeVisible()
    await expect(page.getByText(/Failed to save vitals/i)).not.toBeVisible()

    const nurseHeaders = await authHeaders(request, fixture.nurse_username, fixture.nurse_password)
    const saved = await request.get(`/api/v1/vitals/${fixture.visit_id}`, { headers: nurseHeaders })
    expect(saved.ok()).toBeTruthy()
    const savedVitals = await saved.json()
    expect(savedVitals.status).toBe('draft')
    expect(savedVitals.temperature).toBeCloseTo(37, 5)

    await page.getByRole('button', { name: 'Cancel', exact: true }).click()
    await page.getByText('Nurse Vitals Patient').click()
    await expect(page.locator('input[name="bp_systolic"]')).toHaveValue('120')
    await expect(page.locator('input[name="bp_diastolic"]')).toHaveValue('80')
    await expect(page.locator('input[name="temperature"]')).toHaveValue('98.6')
    await expect(page.locator('input[name="pulse"]')).toHaveValue('72')
  })

  test('blocks incomplete completion without a vitals request', async ({ page }) => {
    await login(page, fixture.nurse_username, fixture.nurse_password, /nurse\/vitals/)
    await expect(page.getByText('Nurse Vitals Patient')).toBeVisible()
    await page.getByText('Nurse Vitals Patient').click()
    const vitalsRequests: string[] = []
    page.on('request', requestItem => {
      if (requestItem.url().includes('/api/v1/vitals') && requestItem.method() === 'POST') vitalsRequests.push(requestItem.postData() ?? '')
    })
    await page.getByRole('button', { name: 'Complete & Send to Doctor', exact: true }).click()
    await expect(page.getByText(/Cannot send to doctor\. Complete:/)).toBeVisible()
    await expect(page.getByText(/Cannot send to doctor\. Complete:/)).toContainText(/Weight|Height|SpO2|Respiratory Rate|Chief Complaint|Allergies\/KNA|Nurse Notes/)
    const firstMissingField = page.locator('input[name="weight"]')
    await expect(firstMissingField).toBeVisible()
    expect(await firstMissingField.evaluate(element => {
      const rect = element.getBoundingClientRect()
      const inViewport = rect.top >= 0 && rect.bottom <= window.innerHeight
      return document.activeElement === element || inViewport
    })).toBeTruthy()
    expect(vitalsRequests).toHaveLength(0)
    expect(await page.getByText('Nurse Vitals Patient').count()).toBeGreaterThan(0)
  })

  test('completes pre-vitals with status completed and hands off to doctor', async ({ page, request }) => {
    await login(page, fixture.nurse_username, fixture.nurse_password, /nurse\/vitals/)
    await expect(page.getByText('Nurse Vitals Patient')).toBeVisible()
    await page.getByText('Nurse Vitals Patient').click()
    await fillCompleteVitals(page)
    const completeRequest = page.waitForRequest(requestItem => requestItem.url().includes('/api/v1/vitals') && requestItem.method() === 'POST')
    const completeResponse = page.waitForResponse(response => response.url().includes('/api/v1/vitals') && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Complete & Send to Doctor', exact: true }).click()
    const requestBody = JSON.parse((await completeRequest).postData() ?? '{}') as { status?: string; temperature?: number }
    expect(requestBody.status).toBe('completed')
    expect(requestBody.temperature).toBe(37)
    expect((await completeResponse).ok()).toBeTruthy()

    await expect(page.getByText('Nurse Vitals Patient')).not.toBeVisible()
    await expect(page.getByText(/Failed to save vitals/i)).not.toBeVisible()

    const nurseHeaders = await authHeaders(request, fixture.nurse_username, fixture.nurse_password)
    const saved = await request.get(`/api/v1/vitals/${fixture.visit_id}`, { headers: nurseHeaders })
    expect(saved.ok()).toBeTruthy()
    const savedVitals = await saved.json()
    expect(savedVitals.status).toBe('completed')
    expect(savedVitals.temperature).toBeCloseTo(37, 5)
    expect(savedVitals.bmi).toBeCloseTo(24.2, 1)
    expect(savedVitals.known_no_allergies).toBe(true)
    expect(savedVitals.completed_at).toBeTruthy()
    expect(savedVitals.recorded_by_user_id).toBe(fixture.nurse_user_id)

    const visit = await request.get(`/api/v1/visits/${fixture.visit_id}`, { headers: nurseHeaders })
    expect((await visit.json()).status).toBe('WAITING_FOR_DOCTOR')
  })

  test('doctor receives the completed patient and duplicate completion is rejected', async ({ page, request }) => {
    const nurseHeaders = await authHeaders(request, fixture.nurse_username, fixture.nurse_password)
    const duplicate = await request.post('/api/v1/vitals', {
      headers: nurseHeaders,
      data: {
        visit_id: fixture.visit_id, status: 'completed', temperature: 37, pulse: 72,
        respiratory_rate: 18, bp_systolic: 120, bp_diastolic: 80, spo2: 98,
        pain_score: 2, height: 170, weight: 70, blood_glucose: 96,
        chief_complaint: 'Fever and cough for two days', allergies: 'None',
        known_no_allergies: true, general_condition: 'Stable',
        level_of_consciousness: 'Alert', nurse_notes: 'Patient stable during pre-vitals',
      },
    })
    expect(duplicate.status()).toBe(409)

    await login(page, fixture.nurse_username, fixture.nurse_password, /nurse\/vitals/)
    await page.getByText('E2E Nurse', { exact: true }).hover()
    await page.getByRole('button', { name: /sign out/i }).click()
    await login(page, fixture.doctor_username, fixture.doctor_password, /doctor\/consultation/)
    await expect(page.getByText('Nurse Vitals Patient')).toBeVisible()
    await page.getByRole('button', { name: /call in/i }).click()
    await expect(page.getByText(/Vitals/).first()).toBeVisible()
    await expect(page.getByText('120/80')).toBeVisible()
    await expect(page.getByText('98.6')).toBeVisible()
    await expect(page.getByText('24.2')).toBeVisible()
    await expect(page.getByText('Fever and cough for two days')).toBeVisible()
    await expect(page.getByText('Patient stable during pre-vitals')).toBeVisible()
  })
})
