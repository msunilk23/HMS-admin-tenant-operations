import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { createHmac } from 'node:crypto'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createPageDiagnostics, type PageDiagnosticsCollector } from './support/pageDiagnostics'

type Ra5Fixture = {
  patient_id: string
  contender_patient_ids: [string, string]
  doctor_id: string
  department_id: string
  lab_test_id: string
  facility_id: string
  other_facility_id: string
  other_facility_lab_order_id: string
  hospital_b_patient_id: string
  hospital_b_visit_id: string
  webhook_invoice_id: string
  webhook_order_id: string
  pharmacy_location_id: string
  slot_date: string
}

const receptionist = { username: 'e2e_receptionist_task7', password: 'E2eReception@123' }
const nurse = { username: 'e2e_nurse_task7', password: 'E2eNurse@123' }
const doctor = { username: 'e2e_doctor_task7', password: 'E2eDoctor@123' }
const labTechnician = { username: 'e2e_lab_task7', password: 'E2eLab@123' }
const billingOfficer = { username: 'e2e_billing_task7', password: 'E2eBilling@123' }
const pharmacist = { username: 'e2e_pharmacist_task7', password: 'E2ePharmacist@123' }
const superAdmin = { username: 'e2e_super_admin_task7', password: 'E2eSuperAdmin@123' }
const task7VisitId = 'a5a85a47-7a23-5587-97de-56daaf8b7822'
const webhookSecret = process.env.RAZORPAY_WEBHOOK_SECRET ?? 'e2e-webhook-secret'
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

test.setTimeout(180_000)

function seedRa5(): Ra5Fixture {
  const output = execFileSync(
    process.env.E2E_PYTHON ?? process.env.PYTHON ?? 'python',
    [path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'), 'seed_ra5_scenario'],
    {
      cwd: path.join(repoRoot, 'backend'),
      encoding: 'utf8',
      env: {
        ...process.env,
        E2E_ENVIRONMENT: 'E2E',
        E2E_ALLOW_DESTRUCTIVE_RESET: 'true',
        DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital',
        SECRET_KEY: process.env.SECRET_KEY ?? 'test-secret-key',
      },
    },
  )
  return JSON.parse(output.trim().split(/\r?\n/).at(-1) ?? '{}') as Ra5Fixture
}

function snapshotVisit(visitId: string) {
  const output = execFileSync(
    process.env.E2E_PYTHON ?? process.env.PYTHON ?? 'python',
    [path.join(repoRoot, 'backend', 'tests', 'e2e_seed_task7.py'), 'snapshot', visitId],
    {
      cwd: path.join(repoRoot, 'backend'),
      encoding: 'utf8',
      env: {
        ...process.env,
        DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://hospital_user:hospital_pass@localhost:5433/hospital',
        SECRET_KEY: process.env.SECRET_KEY ?? 'test-secret-key',
      },
    },
  )
  return JSON.parse(output.trim()) as {
    state: {
      visit_status: string
      pharmacy_queue_count: number
      pharmacy_dispensed_count: number
      pharmacy_invoice_count: number
      audit_records: Array<{ visit_id: string; request_id?: string }>
      lab_order: { status: string; results: Record<string, string>; verified_at: string }
      invoices: Array<{ source: string; status: string; total: string; paid_amount: string; balance: string }>
      payments: Array<{ invoice_id: string; amount: string; payment_method: string; transaction_reference: string; gateway: string }>
      p28: {
        status: string
        item: { prescribed_quantity: string; internal_confirmed_quantity: string; outside_purchase_quantity: string }
        allocations: Array<{ batch_number: string; confirmed_dispensed_quantity: string; available_quantity: string; status: string }>
        ledger_quantities: string[]
      }
    }
  }
}

async function login(page: Page, user = receptionist) {
  await page.goto('/login')
  await page.getByPlaceholder(/you@hospital\.in or mkrish66/i).fill(user.username)
  await page.locator('input[type="password"]').fill(user.password)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page).not.toHaveURL(/login/)
}

async function authHeaders(request: APIRequestContext, user = receptionist) {
  const response = await request.post('/api/v1/auth/login', {
    data: { login_id: user.username, password: user.password },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return { Authorization: `Bearer ${(await response.json()).access_token}` }
}

function webhookBody(fixture: Ra5Fixture, paymentId: string, amount = 25_000) {
  return JSON.stringify({
    event: 'payment.captured',
    payload: {
      payment: {
        entity: {
          id: paymentId,
          order_id: fixture.webhook_order_id,
          amount,
          currency: 'INR',
          status: 'captured',
          method: 'card',
          notes: { tenant_schema: 'e2e_task7', invoice_id: fixture.webhook_invoice_id },
        },
      },
      order: {
        entity: {
          id: fixture.webhook_order_id,
          notes: { tenant_schema: 'e2e_task7', invoice_id: fixture.webhook_invoice_id },
        },
      },
    },
  })
}

async function postWebhook(request: APIRequestContext, body: string, signature?: string) {
  return request.post('/api/v1/billing/razorpay/webhook', {
    data: body,
    headers: {
      'Content-Type': 'application/json',
      'X-Razorpay-Signature': signature ?? createHmac('sha256', webhookSecret).update(body).digest('hex'),
    },
  })
}

test.describe.serial('Release A deterministic OPD chain', () => {
  let fixture: Ra5Fixture
  let diagnostics: PageDiagnosticsCollector
  let visitId = ''

  test.beforeAll(() => { fixture = seedRa5() })
  test.beforeEach(async ({ page }) => { diagnostics = createPageDiagnostics(page) })
  test.afterEach(async ({ page: _page }, info) => { await diagnostics.flush(info) })

  test('Reception books and checks in while capacity remains concurrency-safe', async ({ page, request }) => {
    await login(page)
    await page.goto('/appointments')
    await expect(page.getByRole('heading', { name: 'Appointments' })).toBeVisible()
    await page.getByRole('button', { name: /Book Appointment/ }).click()

    const bookingDialog = page.getByRole('heading', { name: 'Book Appointment' }).locator('..').locator('..')
    await bookingDialog.getByPlaceholder(/Search by name, phone or UHID/).fill('E2E-RA5-CHAIN')
    await page.getByText('RA5 Chain Patient', { exact: true }).click()
    await bookingDialog.locator(`select:has(option[value="${fixture.doctor_id}"])`).selectOption(fixture.doctor_id)
    await bookingDialog.locator('input[type="date"]').fill(fixture.slot_date)
    const firstSlot = bookingDialog.getByRole('button').filter({ hasText: 'available' }).first()
    await expect(firstSlot).toBeEnabled()
    await firstSlot.click()

    const bookedResponse = page.waitForResponse(response =>
      response.url().endsWith('/api/v1/appointments') && response.request().method() === 'POST',
    )
    await bookingDialog.getByRole('button', { name: 'Book Appointment' }).click()
    const booked = await bookedResponse
    expect(booked.status(), await booked.text()).toBe(201)
    const appointment = await booked.json() as { id: string }

    const headers = await authHeaders(request)
    const slotsResponse = await request.get('/api/v1/appointments/slots', {
      headers,
      params: { doctor_id: fixture.doctor_id, date: fixture.slot_date },
    })
    expect(slotsResponse.ok(), await slotsResponse.text()).toBeTruthy()
    const slots = await slotsResponse.json() as Array<{ slot_time: string; is_available: boolean }>
    const contentionSlot = slots.find(slot => slot.is_available)
    expect(contentionSlot).toBeTruthy()

    const attempts = await Promise.all(fixture.contender_patient_ids.map(patientId => request.post('/api/v1/appointments', {
      headers,
      data: {
        patient_id: patientId,
        doctor_id: fixture.doctor_id,
        slot_time: contentionSlot!.slot_time,
        type: 'phone',
        notes: 'RA-5 concurrent capacity proof',
      },
    })))
    expect(attempts.map(response => response.status()).sort()).toEqual([201, 409])

    await page.locator('main input[type="date"]').fill(fixture.slot_date)
    const patientCard = page.getByText('RA5 Chain Patient', { exact: true }).locator('..').locator('..')
    await expect(patientCard).toContainText('scheduled')
    await patientCard.getByRole('button', { name: 'Check In' }).click()
    await expect(page.getByRole('heading', { name: 'Confirm Check-In' })).toBeVisible()
    const checkInResponse = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/appointments/${appointment.id}/checkin`) && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: 'Confirm & Check In' }).click()
    const checkedIn = await checkInResponse
    expect(checkedIn.ok(), await checkedIn.text()).toBeTruthy()
    const result = await checkedIn.json() as { visit_id: string }
    visitId = result.visit_id
    expect(visitId).toMatch(/^[0-9a-f-]{36}$/)
    await expect(page).toHaveURL(/queue/)
    const queueRow = page.getByRole('row').filter({ hasText: 'RA5 Chain Patient' })
    await expect(queueRow).toContainText('checked in')
  })

  test('Nurse records complete pre-vitals and hands the same visit to Doctor', async ({ page, request }) => {
    expect(visitId).toBeTruthy()
    await login(page, nurse)
    await page.goto('/nurse/vitals')
    await expect(page.getByText('RA5 Chain Patient', { exact: true })).toBeVisible()
    await page.getByText('RA5 Chain Patient', { exact: true }).click()
    await page.locator('input[name="bp_systolic"]').fill('120')
    await page.locator('input[name="bp_diastolic"]').fill('80')
    await page.locator('input[name="temperature"]').fill('98.6')
    await page.locator('input[name="pulse"]').fill('72')
    await page.locator('input[name="spo2"]').fill('98')
    await page.locator('input[name="respiratory_rate"]').fill('18')
    await page.locator('input[name="weight"]').fill('70')
    await page.locator('input[name="height"]').fill('170')
    await page.locator('input[name="pain_score"]').fill('2')
    await page.locator('input[name="blood_glucose"]').fill('96')
    await page.locator('textarea[name="chief_complaint"]').fill('RA-5 fever and cough')
    await page.locator('input[name="known_no_allergies"]').check()
    await page.locator('select[name="general_condition"]').selectOption('Stable')
    await page.locator('select[name="level_of_consciousness"]').selectOption('Alert')
    await page.locator('textarea[name="nurse_notes"]').fill('RA-5 patient stable for Doctor handoff')

    const completedResponse = page.waitForResponse(response =>
      response.url().includes('/api/v1/vitals') && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: 'Complete & Send to Doctor', exact: true }).click()
    const completed = await completedResponse
    expect(completed.ok(), await completed.text()).toBeTruthy()
    await expect(page.getByText('RA5 Chain Patient', { exact: true })).not.toBeVisible()

    const headers = await authHeaders(request, nurse)
    const visit = await request.get(`/api/v1/visits/${visitId}`, { headers })
    expect(visit.ok(), await visit.text()).toBeTruthy()
    expect((await visit.json()).status).toBe('WAITING_FOR_DOCTOR')
  })

  test('Doctor records controlled diagnosis, medicine, and Lab order for the same visit', async ({ page, request }) => {
    expect(visitId).toBeTruthy()
    await login(page, doctor)
    await page.goto('/doctor/consultation')
    await expect(page.getByText('RA5 Chain Patient', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: /call in/i }).click()
    await expect(page.getByPlaceholder(/what brings the patient in today/i)).toBeVisible()
    await page.getByPlaceholder(/what brings the patient in today/i).fill('RA-5 fever and cough consultation')
    await page.getByRole('button', { name: /add diagnosis/i }).click()
    const diagnosis = page.getByPlaceholder(/search icd-10 code or description/i).first()
    await diagnosis.fill('E2E.J06.9')
    await page.getByRole('button', { name: /E2E\.J06\.9/i }).click()

    const consultationResponse = page.waitForResponse(response =>
      response.url().includes('/api/v1/consultations') && ['POST', 'PATCH'].includes(response.request().method()),
    )
    await page.getByRole('button', { name: /save & write prescription/i }).click()
    const consultation = await consultationResponse
    expect(consultation.ok(), await consultation.text()).toBeTruthy()
    await expect(page).toHaveURL(new RegExp(`/doctor/prescription/${visitId}`))

    await page.getByRole('button', { name: /add medicine/i }).click()
    const medicineSearch = page.getByPlaceholder(/search formulary generic, brand or composition/i).first()
    await medicineSearch.fill('E2E Dolo')
    await page.getByRole('button', { name: /E2E Paracetamol.*500.*Tablet/i }).click()
    await page.getByPlaceholder(/e\.g\. 500mg/i).first().fill('1')
    await page.getByPlaceholder(/e\.g\. 10/i).first().fill('10')

    await page.getByRole('button', { name: 'Add Test' }).click()
    const labSearch = page.getByPlaceholder(/search lab test by code, name, or category/i)
    await labSearch.fill('RA5-CBC')
    await page.getByRole('button', { name: /RA5-CBC.*RA5 Complete Blood Count/i }).click()
    await page.getByPlaceholder(/Instructions \/ notes/).fill('RA-5 deterministic collection')

    const prescriptionResponse = page.waitForResponse(response =>
      response.url().endsWith('/api/v1/prescriptions') && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: 'Save Prescription' }).click()
    const prescription = await prescriptionResponse
    expect(prescription.status(), await prescription.text()).toBe(201)
    await expect(page).toHaveURL(/doctor\/consultation/)

    const headers = await authHeaders(request, doctor)
    const savedPrescription = await request.get(`/api/v1/prescriptions/${visitId}`, { headers })
    expect(savedPrescription.ok(), await savedPrescription.text()).toBeTruthy()
    const prescriptionBody = await savedPrescription.json() as { items: Array<{ medicine_product_id?: string; final_quantity?: string }>; lab_tests?: Array<{ test_id: string }> }
    expect(prescriptionBody.items).toEqual(expect.arrayContaining([
      expect.objectContaining({ final_quantity: '10' }),
    ]))
    expect(prescriptionBody.lab_tests).toEqual(expect.arrayContaining([
      expect.objectContaining({ test_id: fixture.lab_test_id }),
    ]))

    const visit = await request.get(`/api/v1/visits/${visitId}`, { headers })
    expect(visit.ok(), await visit.text()).toBeTruthy()
    expect((await visit.json()).status).toBe('CONSULTATION_COMPLETED')
  })

  test('Lab Technician completes the lifecycle and Doctor sees the verified result', async ({ page, request }) => {
    expect(visitId).toBeTruthy()
    await login(page, labTechnician)
    await page.goto('/lab')
    await expect(page.getByRole('heading', { name: 'Laboratory Orders' })).toBeVisible()
    await expect(page.getByText('RA5 Chain Patient', { exact: true })).toBeVisible()

    for (const [buttonName, endpointSuffix] of [
      ['Await Sample', '/status'],
      ['Collect Sample', '/status'],
      ['Start Processing', '/status'],
    ] as const) {
      const responsePromise = page.waitForResponse(response =>
        response.url().includes('/api/v1/lab/')
        && response.url().includes(endpointSuffix)
        && response.request().method() === 'PATCH',
      )
      await page.getByRole('button', { name: buttonName }).click()
      const response = await responsePromise
      expect(response.ok(), await response.text()).toBeTruthy()
      await expect(page.getByRole('button', {
        name: buttonName === 'Await Sample' ? 'Collect Sample' : buttonName === 'Collect Sample' ? 'Start Processing' : 'Enter Results',
      })).toBeVisible()
    }

    await page.getByRole('button', { name: 'Enter Results' }).click()
    await expect(page.getByRole('heading', { name: 'Enter Lab Results' })).toBeVisible()
    await page.getByPlaceholder('Enter value…').fill('7.4')
    await page.getByPlaceholder(/Observations, sample quality/).fill('RA-5 sample processed successfully')
    const resultsResponse = page.waitForResponse(response =>
      response.url().includes('/api/v1/lab/') && response.url().endsWith('/results') && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: 'Save Results' }).click()
    const results = await resultsResponse
    expect(results.status(), await results.text()).toBe(201)

    await page.getByText(/resulted orders/).click()
    await expect(page.getByRole('button', { name: 'Verify Results' })).toBeVisible()
    const verifyResponse = page.waitForResponse(response =>
      response.url().includes('/api/v1/lab/') && response.url().endsWith('/verify') && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: 'Verify Results' }).click()
    const verified = await verifyResponse
    expect(verified.ok(), await verified.text()).toBeTruthy()
    await expect(page.getByText('verified', { exact: true })).toBeVisible()

    const labHeaders = await authHeaders(request, labTechnician)
    const ordersResponse = await request.get('/api/v1/lab', { headers: labHeaders, params: { visit_id: visitId } })
    expect(ordersResponse.ok(), await ordersResponse.text()).toBeTruthy()
    const orders = await ordersResponse.json() as Array<{ id: string; status: string }>
    expect(orders).toHaveLength(1)
    expect(orders[0].status).toBe('verified')

    await login(page, doctor)
    await page.goto('/doctor/lab-results')
    await page.getByLabel('Select Patient/Visit').selectOption(visitId)
    const resultRow = page.getByRole('row').filter({ hasText: 'RA5-CBC' })
    await expect(resultRow).toContainText('RA5 Complete Blood Count')
    await expect(resultRow).toContainText('7.4')
    await expect(resultRow).toContainText('VERIFIED')
  })

  test('Billing receives the exact Lab charge and records payment', async ({ page, request }) => {
    expect(visitId).toBeTruthy()
    await login(page, billingOfficer)
    await page.goto(`/billing?visitId=${visitId}&source=lab`)
    await expect(page.getByRole('heading', { name: 'Invoice Summary' })).toBeVisible()
    await expect(page.getByText('RA5-CBC: RA5 Complete Blood Count')).toBeVisible()
    await expect(page.getByText('₹250.00', { exact: true }).first()).toBeVisible()

    const paymentResponse = page.waitForResponse(response =>
      response.url().includes('/api/v1/billing/') && response.url().endsWith('/pay') && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: 'Cash' }).click()
    await page.getByRole('button', { name: /Confirm Payment.*250\.00/ }).click()
    const payment = await paymentResponse
    expect(payment.ok(), await payment.text()).toBeTruthy()
    await expect(page.getByRole('heading', { name: 'Payment Received' })).toBeVisible()

    const headers = await authHeaders(request, billingOfficer)
    const invoicesResponse = await request.get('/api/v1/billing', { headers, params: { visit_id: visitId } })
    expect(invoicesResponse.ok(), await invoicesResponse.text()).toBeTruthy()
    const invoices = await invoicesResponse.json() as Array<{ source?: string; status: string; total: number; paid_amount: number }>
    const labInvoice = invoices.find(invoice => invoice.source === 'lab')
    expect(labInvoice).toMatchObject({ status: 'paid', total: 250, paid_amount: 250 })
  })

  test('Nurse dispatches and Pharmacy completes FEFO dispensing for the same visit', async ({ page }) => {
    expect(visitId).toBeTruthy()
    await login(page, nurse)
    await page.goto('/nurse/vitals')
    const dispatchCard = page.locator('div.rounded-xl').filter({ hasText: 'RA5 Chain Patient' }).filter({
      has: page.getByRole('button', { name: /Pharmacy/ }),
    })
    await expect(dispatchCard).toBeVisible()
    const dispatchResponse = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/visits/${visitId}/dispatch`) && response.request().method() === 'POST',
    )
    await dispatchCard.getByRole('button', { name: /Pharmacy/ }).click()
    await expect(page.getByRole('heading', { name: 'Send to Pharmacy?' })).toBeVisible()
    await page.getByRole('button', { name: 'Yes, Send to Pharmacy' }).click()
    const dispatched = await dispatchResponse
    expect(dispatched.ok(), await dispatched.text()).toBeTruthy()

    await login(page, pharmacist)
    await page.goto('/pharmacy')
    await expect(page.getByText('RA5 Chain Patient', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Dispense' }).click()
    await page.getByLabel('Facility ID').fill(fixture.facility_id)
    await page.getByLabel('Pharmacy location ID').fill(fixture.pharmacy_location_id)
    await page.getByRole('button', { name: 'Start review' }).click()
    await page.getByRole('button', { name: /validate and reserve fefo stock/i }).click()
    await expect(page.getByText(/ready for billing/i)).toBeVisible()
    await page.getByRole('button', { name: 'Create invoice' }).click()
    await expect(page.getByText(/invoice paid/i)).toBeVisible()
    await expect(page.getByText(/stock and ledger updated/i)).toBeVisible()
    await page.reload()
    await expect(page.getByText(/dispensed orders today/i)).toBeVisible()

    const snapshot = snapshotVisit(visitId).state
    expect(snapshot.visit_status).toBe('CONSULTATION_COMPLETED')
    expect(snapshot.lab_order).toMatchObject({ status: 'verified', results: { 'RA5-CBC': '7.4' } })
    expect(snapshot.lab_order.verified_at).toBeTruthy()
    expect(snapshot.invoices).toEqual(expect.arrayContaining([
      expect.objectContaining({ source: 'lab', status: 'paid', total: '250.00', paid_amount: '250.00', balance: '0.00' }),
      expect.objectContaining({ source: 'pharmacy_dispense', status: 'paid' }),
    ]))
    expect(snapshot.pharmacy_queue_count).toBe(1)
    expect(snapshot.pharmacy_dispensed_count).toBe(1)
    expect(snapshot.pharmacy_invoice_count).toBe(1)
    expect(snapshot.p28.status).toBe('CONFIRMED')
    expect(snapshot.p28.item).toMatchObject({
      prescribed_quantity: '10.000',
      internal_confirmed_quantity: '10.000',
      outside_purchase_quantity: '0.000',
    })
    expect(snapshot.p28.allocations).toEqual([
      expect.objectContaining({
        batch_number: 'RA4-OTC-FEFO',
        confirmed_dispensed_quantity: '10.000',
        available_quantity: '10.000',
        status: 'CONSUMED',
      }),
    ])
    expect(snapshot.p28.ledger_quantities).toEqual(['-10.000'])
    expect(snapshot.audit_records.length).toBeGreaterThan(5)
    expect(snapshot.audit_records.every(record => record.visit_id === visitId && record.request_id)).toBeTruthy()
  })

  test('Super Admin is denied tenant operational data', async ({ request }) => {
    const headers = await authHeaders(request, superAdmin)
    const visits = await request.get('/api/v1/visits', { headers })
    expect(visits.status()).toBe(403)
    expect(await visits.json()).toMatchObject({ detail: expect.stringMatching(/super admin cannot access tenant resources/i) })
  })

  test('Reception role cannot create a consultation', async ({ request }) => {
    const headers = await authHeaders(request, receptionist)
    const consultation = await request.post('/api/v1/consultations', {
      headers,
      data: { visit_id: visitId, chief_complaint: 'RA-5 authorization denial' },
    })
    expect(consultation.status()).toBe(403)
    expect(await consultation.json()).toMatchObject({ detail: 'Insufficient permissions' })
  })

  test('Hospital A cannot retrieve Hospital B direct IDs or override its tenant context', async ({ request }) => {
    const headers = await authHeaders(request, doctor)
    const crossPatient = await request.get(`/api/v1/patients/${fixture.hospital_b_patient_id}`, { headers })
    const crossVisit = await request.get(`/api/v1/visits/${fixture.hospital_b_visit_id}`, {
      headers: { ...headers, 'X-Tenant-Schema': 'e2e_task7_b' },
    })
    expect([403, 404]).toContain(crossPatient.status())
    expect([403, 404]).toContain(crossVisit.status())
    const responseText = `${await crossPatient.text()} ${await crossVisit.text()}`
    expect(responseText).not.toContain('Hospital B')
    expect(responseText).not.toContain(fixture.hospital_b_patient_id)
  })

  test('Lab Technician cannot mutate an order from another facility', async ({ request }) => {
    const headers = await authHeaders(request, labTechnician)
    const crossFacility = await request.patch(
      `/api/v1/lab/${fixture.other_facility_lab_order_id}/status?new_status=sample_pending`,
      { headers },
    )
    expect(crossFacility.status()).toBe(404)
    expect(await crossFacility.json()).toMatchObject({ detail: 'Lab order not found' })

    const visibleOrders = await request.get('/api/v1/lab', { headers })
    expect(visibleOrders.ok(), await visibleOrders.text()).toBeTruthy()
    expect((await visibleOrders.json()).some((order: { id: string }) => order.id === fixture.other_facility_lab_order_id)).toBeFalsy()
  })

  test('Razorpay webhook rejects tampering and processes one payment idempotently', async ({ request }) => {
    const validBody = webhookBody(fixture, 'pay_ra5_captured_250')
    const invalidSignature = await postWebhook(request, validBody, 'tampered-signature')
    expect(invalidSignature.status()).toBe(400)

    const wrongAmountBody = webhookBody(fixture, 'pay_ra5_wrong_amount', 24_999)
    const wrongAmount = await postWebhook(request, wrongAmountBody)
    expect(wrongAmount.status()).toBe(400)
    expect(await wrongAmount.json()).toMatchObject({ detail: /amount or currency does not match/i })

    const captured = await postWebhook(request, validBody)
    expect(captured.status(), await captured.text()).toBe(200)
    expect(await captured.json()).toEqual({ status: 'ok' })

    const retry = await postWebhook(request, validBody)
    expect(retry.status(), await retry.text()).toBe(200)

    const replay = await postWebhook(request, webhookBody(fixture, 'pay_ra5_replay_other'))
    expect(replay.status()).toBe(409)
    expect(await replay.json()).toMatchObject({ detail: /already paid by a different payment/i })

    const snapshot = snapshotVisit(task7VisitId).state
    expect(snapshot.invoices).toEqual(expect.arrayContaining([
      expect.objectContaining({ source: 'consultation', status: 'paid', total: '250.00', paid_amount: '250.00' }),
    ]))
    expect(snapshot.payments.filter(payment => payment.invoice_id === fixture.webhook_invoice_id)).toEqual([
      expect.objectContaining({
        amount: '250.00',
        payment_method: 'card',
        transaction_reference: 'pay_ra5_captured_250',
        gateway: 'razorpay',
      }),
    ])
  })
})