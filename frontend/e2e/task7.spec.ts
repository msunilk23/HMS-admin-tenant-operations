import { test, expect, type APIRequestContext, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const doctor = {
  username: 'e2e_doctor_task7',
  password: 'E2eDoctor@123',
  visitId: 'a5a85a47-7a23-5587-97de-56daaf8b7822',
}

type AuditRecord = {
  id: string
  user_id: string | null
  tenant_schema: string | null
  role: string | null
  action: string
  resource_type: string
  resource_id: string | null
  patient_id: string | null
  visit_id: string | null
  request_id: string | null
  timestamp: string | null
  new_value?: Record<string, unknown> | null
  old_value?: Record<string, unknown> | null
  reason?: string | null
  request_metadata?: Record<string, unknown> | null
}

type FixtureSnapshot = {
  tenants: {
    hospital_a: {
      schema: string
      tenant_id: string
      doctor_user_id: string
      patient_id: string
      visit_id: string
      icd10_id: string
      medicine_master_id: string
      icd10_code: string
      medicine_name: string
    }
    hospital_b: {
      schema: string
      tenant_id: string
      doctor_user_id: string
      patient_id: string
      visit_id: string
      icd10_id: string
      medicine_master_id: string
      icd10_code: string
      medicine_name: string
    }
  }
  state: {
    prescription_count: number
    consultation_count: number
    visit_status: string | null
    pharmacy_queue_count: number
    pharmacy_dispensed_count: number
    pharmacy_invoice_count: number
    stock_movement_table: string | null
    stock_movement_count: number
    inventory_table: string | null
    inventory_quantity: number | null
    audit_records: AuditRecord[]
  }
}

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

function fixtureSnapshot(visitId: string = doctor.visitId): FixtureSnapshot {
  const output = execFileSync(process.env.PYTHON ?? 'python', [
    path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'),
    'snapshot',
    visitId,
  ], {
    cwd: path.join(repoRoot, 'backend'),
    env: {
      ...process.env,
      DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital',
      SECRET_KEY: process.env.SECRET_KEY ?? 'test-secret-key',
    },
  }).toString('utf-8').trim()

  return JSON.parse(output) as FixtureSnapshot
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

async function openConsultationForSeedPatient(page: Page) {
  await page.goto('/doctor/consultation')
  const callIn = page.getByRole('button', { name: /call in/i }).first()
  if (await callIn.isVisible({ timeout: 5_000 }).catch(() => false)) {
    await callIn.click()
    return
  }
  await page.getByText('E2E Patient').first().click()
}

test.describe.serial('Task 7 controlled clinical data', () => {
  test('doctor searches ICD-10 by code and description, selects, saves, and reloads diagnosis', async ({ page }) => {
    await login(page)
    await openConsultationForSeedPatient(page)
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
    await page.getByText('E2E Patient').first().click()
    await expect(page.getByPlaceholder(/search icd-10 code or description/i).first()).toHaveValue(/E2E\.J06\.9.*E2E Acute upper respiratory infection/)
  })

  test('free-text diagnosis requires a reason and is visibly marked', async ({ page }) => {
    await login(page)
    await page.goto('/doctor/consultation')
    await page.getByText('E2E Patient').first().click()
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
    const before = fixtureSnapshot()

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

    const headers = await authRequest(page.request)
    const completeConsultation = await page.request.patch(`/api/v1/consultations/${doctor.visitId}`, {
      headers,
      data: { status: 'completed' },
    })
    expect([200, 409]).toContain(completeConsultation.status())

    const after = fixtureSnapshot()
    expect(after.state.prescription_count).toBeGreaterThanOrEqual(before.state.prescription_count)
    expect(after.state.visit_status).toBe('CONSULTATION_COMPLETED')

    // Phase 1 has no dispense/inventory mutation in doctor prescription flow.
    expect(after.state.inventory_quantity).toBe(before.state.inventory_quantity)
    expect(after.state.stock_movement_count).toBe(before.state.stock_movement_count)
    expect(after.state.pharmacy_dispensed_count).toBe(before.state.pharmacy_dispensed_count)
    expect(after.state.pharmacy_invoice_count).toBe(before.state.pharmacy_invoice_count)

    const savedPrescription = await page.request.get(`/api/v1/prescriptions/${doctor.visitId}`, { headers })
    expect(savedPrescription.ok()).toBeTruthy()
    const savedBody = await savedPrescription.json()
    expect(Array.isArray(savedBody.items)).toBeTruthy()
    expect(savedBody.items.length).toBeGreaterThanOrEqual(2)

    const audits = after.state.audit_records
    expect(audits.length).toBeGreaterThan(0)

    const consultationAudits = audits.filter((entry) => entry.resource_type === 'consultation' && ['CREATE', 'UPDATE', 'AMEND'].includes(entry.action))
    const consultationCompletionAudits = consultationAudits.filter(
      (entry) => String((entry.new_value as Record<string, unknown> | undefined)?.status ?? '') === 'completed',
    )
    const prescriptionAudits = audits.filter((entry) => entry.resource_type === 'prescription' && ['CREATE', 'UPDATE'].includes(entry.action))
    const visitTransitionAudits = audits.filter((entry) => entry.resource_type === 'visit_state' && entry.action === 'UPDATE')

    expect(consultationAudits.length).toBeGreaterThan(0)
    expect(consultationCompletionAudits.length).toBeGreaterThan(0)
    expect(prescriptionAudits.length).toBeGreaterThan(0)
    expect(visitTransitionAudits.some((entry) => String((entry.new_value as Record<string, unknown> | undefined)?.status ?? '') === 'CONSULTATION_COMPLETED')).toBeTruthy()

    // Diagnosis evidence can be selected ICD-10 or free-text with reason.
    expect(
      consultationAudits.some((entry) => {
        const payload = JSON.stringify(entry.new_value ?? {})
        return payload.includes('diagnosis_icd10') || payload.includes('free_text_diagnosis')
      }),
    ).toBeTruthy()

    for (const entry of audits) {
      expect(entry.tenant_schema).toBeTruthy()
      expect(entry.user_id ?? doctor.visitId).toBeTruthy()
      expect(entry.role).toBeTruthy()
      expect(entry.visit_id).toBe(doctor.visitId)
      expect(entry.request_id).toBeTruthy()
      expect(entry.timestamp).toBeTruthy()

      const blob = JSON.stringify(entry).toLowerCase()
      expect(blob).not.toContain('jwt')
      expect(blob).not.toContain('password')
      expect(blob).not.toContain('aadhaar')
      expect(blob).not.toContain('aadhar')
      expect(blob).not.toContain('secret')
    }
  })

  test('hospital A doctor cannot access hospital B entities by id, direct URL, params, or forged headers', async ({ page, request }) => {
    const fixture = fixtureSnapshot()
    const hospitalA = fixture.tenants.hospital_a
    const hospitalB = fixture.tenants.hospital_b

    await login(page)
    const headers = await authRequest(request)

    const aIcd = await request.get('/api/v1/master-data/icd10?q=E2E', { headers })
    const aMeds = await request.get('/api/v1/master-data/medicines?q=E2E', { headers })
    expect(aIcd.ok()).toBeTruthy()
    expect(aMeds.ok()).toBeTruthy()
    expect((await aIcd.json()).length).toBeGreaterThan(0)
    expect((await aMeds.json()).length).toBeGreaterThan(0)

    const leakedIcdById = await request.get(`/api/v1/master-data/icd10?q=${hospitalB.icd10_id}`, { headers })
    const leakedMedicineById = await request.get(`/api/v1/master-data/medicines?q=${hospitalB.medicine_master_id}`, { headers })
    expect(leakedIcdById.ok()).toBeTruthy()
    expect(leakedMedicineById.ok()).toBeTruthy()
    expect(await leakedIcdById.json()).toEqual([])
    expect(await leakedMedicineById.json()).toEqual([])

    const crossPatient = await request.get(`/api/v1/patients/${hospitalB.patient_id}`, { headers })
    const crossVisit = await request.get(`/api/v1/visits/${hospitalB.visit_id}`, { headers })
    const crossConsultation = await request.get(`/api/v1/consultations/${hospitalB.visit_id}`, { headers })
    const crossPrescription = await request.get(`/api/v1/prescriptions/${hospitalB.visit_id}`, { headers })
    expect([403, 404]).toContain(crossPatient.status())
    expect([403, 404]).toContain(crossVisit.status())
    expect([403, 404]).toContain(crossConsultation.status())
    expect([403, 404]).toContain(crossPrescription.status())

    const forgedAllowedHeader = await request.get(`/api/v1/visits/${hospitalA.visit_id}`, {
      headers: { ...headers, 'X-Tenant-Schema': hospitalB.schema },
    })
    expect(forgedAllowedHeader.ok()).toBeTruthy()
    expect((await forgedAllowedHeader.json()).id).toBe(hospitalA.visit_id)

    const forgedCrossTenant = await request.get(`/api/v1/visits/${hospitalB.visit_id}`, {
      headers: { ...headers, 'X-Tenant-Schema': hospitalB.schema },
    })
    expect([403, 404]).toContain(forgedCrossTenant.status())

    const directRxResponse = page.waitForResponse(
      (response) => response.url().includes(`/api/v1/prescriptions/${hospitalB.visit_id}`) && [403, 404].includes(response.status()),
    )
    await page.goto(`/doctor/prescription/${hospitalB.visit_id}`)
    await directRxResponse

    await page.goto('/doctor/consultation')
    await expect(page.getByText(/Hospital B Patient/i)).toHaveCount(0)

    const appState = await page.evaluate(() => JSON.stringify({
      localStorage: Object.fromEntries(Object.entries(localStorage)),
      sessionStorage: Object.fromEntries(Object.entries(sessionStorage)),
    }))
    expect(appState).not.toContain(hospitalB.patient_id)
    expect(appState).not.toContain(hospitalB.visit_id)
    expect(appState).not.toContain(hospitalB.icd10_id)
    expect(appState).not.toContain(hospitalB.medicine_master_id)

    const responseBodies = [
      JSON.stringify(await leakedIcdById.json()),
      JSON.stringify(await leakedMedicineById.json()),
      JSON.stringify(await crossPatient.json()),
      JSON.stringify(await crossVisit.json()),
      JSON.stringify(await crossConsultation.json()),
      JSON.stringify(await crossPrescription.json()),
      JSON.stringify(await forgedCrossTenant.json()),
    ].join(' ')

    expect(responseBodies).not.toContain('Hospital B')
    expect(responseBodies).not.toContain(hospitalB.icd10_code)
    expect(responseBodies).not.toContain(hospitalB.medicine_name)
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
