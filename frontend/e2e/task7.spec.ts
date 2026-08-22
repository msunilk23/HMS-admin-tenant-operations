import { test, expect, type APIRequestContext, type Page } from '@playwright/test'

const doctor = {
  username: 'e2e_doctor_task7',
  password: 'E2eDoctor@123',
  visitId: 'a5a85a47-7a23-5587-97de-56daaf8b7822',
}

async function login(page: Page) {
  await page.goto('/login')
  await page.getByPlaceholder(/you@hospital\.in or mkrish66/i).fill(doctor.username)
  await page.locator('input[type="password"]').fill(doctor.password)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page).toHaveURL(/doctor/)
}

async function authRequest(request: APIRequestContext) {
  const response = await request.post('/api/v1/auth/login', { data: { login_id: doctor.username, password: doctor.password } })
  expect(response.ok()).toBeTruthy()
  const token = (await response.json()).access_token
  return { Authorization: `Bearer ${token}` }
}

async function loginAs(request: APIRequestContext, username: string, password: string) {
  const response = await request.post('/api/v1/auth/login', { data: { login_id: username, password } })
  expect(response.ok()).toBeTruthy()
  return { Authorization: `Bearer ${(await response.json()).access_token}` }
}

test.describe.serial('Task 7 controlled clinical data', () => {
  test('doctor searches ICD-10 by code and description, selects, saves, and reloads diagnosis', async ({ page }) => {
    await login(page)
    await page.goto('/doctor/consultation')
    await page.getByRole('button', { name: /call in/i }).first().click()
    await page.getByRole('button', { name: /add diagnosis/i }).click()

    const diagnosis = page.getByPlaceholder(/search icd-10 code or description/i).first()
    await diagnosis.fill('J06')
    await expect(page.getByText(/E2E\.J06\.9/)).toBeVisible()
    await page.getByRole('button', { name: /E2E\.J06\.9/i }).click()
    await expect(diagnosis).toHaveValue(/E2E\.J06\.9.*E2E Acute upper respiratory infection/)

    await page.getByPlaceholder(/what brings the patient in today/i).fill('E2E cough follow-up')
    await page.getByRole('button', { name: /save & write prescription/i }).click()
    await expect(page).toHaveURL(/doctor\/prescription/)

    await page.goto('/doctor/consultation')
    await page.getByRole('button').filter({ hasText: 'E2E Patient' }).first().click()
    await expect(page.getByPlaceholder(/search icd-10 code or description/i).first()).toHaveValue(/E2E\.J06\.9.*E2E Acute upper respiratory infection/)
  })

  test('free-text diagnosis requires a reason and is visibly marked', async ({ page }) => {
    await login(page)
    await page.goto('/doctor/consultation')
    await page.getByRole('button').filter({ hasText: 'E2E Patient' }).first().click()
    await page.getByRole('button', { name: /free-text diagnosis/i }).first().click()
    await page.getByPlaceholder('Free-text diagnosis', { exact: true }).fill('E2E uncommon syndrome')
    await page.getByRole('button', { name: /save & write prescription/i }).click()
    await expect(page.getByPlaceholder(/reason for using free-text diagnosis/i)).toBeVisible()
    await page.getByPlaceholder(/reason for using free-text diagnosis/i).fill('No suitable ICD-10 code exists')
    await expect(page).toHaveURL(/doctor\/consultation/)
    await page.locator('form').getByRole('button', { name: /save & write prescription/i }).click()
    await expect(page).toHaveURL(/doctor\/prescription/)
  })

  test('doctor searches distinct medicines, fills multiple rows, and reloads prescription details', async ({ page }) => {
    await login(page)
    await page.goto(`/doctor/prescription/${doctor.visitId}`)
    const medicineSearch = page.getByPlaceholder(/search generic, brand, strength or form/i).first()
    await page.getByRole('button', { name: /add medicine/i }).click()
    await medicineSearch.fill('E2E Paracetamol')
    await expect(page.getByText(/500 mg.*Tablet/)).toBeVisible()
    await page.getByRole('button', { name: /E2E Paracetamol.*500 mg.*Tablet/i }).click()
    await page.getByPlaceholder(/e\.g\. 500mg/i).first().fill('1')
    await page.locator('select').nth(0).selectOption({ label: '5 days' })
    await page.getByPlaceholder(/e\.g\. 10/i).first().fill('5')
    await page.getByRole('button', { name: /add medicine/i }).click()
    const secondSearch = page.getByPlaceholder(/search generic, brand, strength or form/i).nth(1)
    await secondSearch.fill('E2E Crocin')
    await expect(page.getByText(/650 mg.*Capsule/)).toBeVisible()
    await page.getByRole('button', { name: /E2E Paracetamol.*650 mg.*Capsule/i }).click()
    await page.getByPlaceholder(/e\.g\. 500mg/i).nth(1).fill('1')
    await page.locator('select').nth(2).selectOption({ label: '3 days' })
    await page.getByPlaceholder(/e\.g\. 10/i).nth(1).fill('3')
    await page.getByRole('button', { name: /save prescription|complete/i }).click()
    await expect(page).toHaveURL(/doctor\/consultation/)

    await page.goto(`/doctor/prescription/${doctor.visitId}`)
    await expect(page.getByText(/E2E Paracetamol/).first()).toBeVisible()
    await expect(page.getByText(/500 mg/).first()).toBeVisible()
  })

  test('inactive medicine is absent and non-doctor access is rejected by real APIs', async ({ request }) => {
    const headers = await authRequest(request)
    const medicines = await request.get('/api/v1/master-data/medicines?q=inactive', { headers })
    expect(medicines.ok()).toBeTruthy()
    expect(await medicines.json()).toEqual([])

    const receptionistHeaders = await loginAs(request, 'e2e_receptionist_task7', 'E2eReception@123')
    const consultation = await request.post('/api/v1/consultations', {
      headers: receptionistHeaders,
      data: { visit_id: doctor.visitId, chief_complaint: 'authorization check' },
    })
    expect(consultation.status()).toBe(403)
  })

  test('invalid session and forged tenant header cannot access controlled data', async ({ page, request }) => {
    await login(page)
    const headers = await authRequest(request)
    const invalid = await request.get('/api/v1/master-data/icd10?q=E2E', { headers: { Authorization: 'Bearer malformed.token.value' } })
    expect(invalid.status()).toBe(401)
    const forged = await request.get('/api/v1/master-data/medicines?q=E2E', {
      headers: { ...headers, 'X-Tenant-Schema': 'hospital_b' },
    })
    expect(forged.ok()).toBeTruthy()
    const body = await forged.json()
    expect(body.every((item: { generic_name: string }) => item.generic_name.startsWith('E2E'))).toBeTruthy()
    expect(JSON.stringify(body)).not.toContain('Hospital B')

    const changed = await request.post('/api/v1/auth/change-password', {
      headers,
      data: { current_password: doctor.password, new_password: 'E2eDoctor@456' },
    })
    expect(changed.ok()).toBeTruthy()
    const oldSession = await request.get('/api/v1/master-data/icd10?q=E2E', { headers })
    expect(oldSession.status()).toBe(401)
    await page.reload()
    await expect(page).toHaveURL(/login/)
  })
})
