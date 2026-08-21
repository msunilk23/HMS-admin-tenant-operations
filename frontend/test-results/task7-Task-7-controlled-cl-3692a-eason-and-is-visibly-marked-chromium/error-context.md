# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: task7.spec.ts >> Task 7 controlled clinical data >> free-text diagnosis requires a reason and is visibly marked
- Location: e2e\task7.spec.ts:46:3

# Error details

```
Test timeout of 30000ms exceeded.
```

```
Error: locator.click: Test timeout of 30000ms exceeded.
Call log:
  - waiting for locator('form').getByRole('button', { name: /save & write prescription/i })

```

# Page snapshot

```yaml
- generic [ref=f1e3]:
  - complementary [ref=f1e4]:
    - button "Expand sidebar" [ref=f1e6] [cursor=pointer]
    - navigation [ref=f1e9]:
      - list [ref=f1e10]:
        - listitem [ref=f1e11]:
          - link "Consultation" [ref=f1e12] [cursor=pointer]:
            - /url: /doctor/consultation
        - listitem [ref=f1e15]:
          - link "Indent" [ref=f1e16] [cursor=pointer]:
            - /url: /indent
  - main [ref=f1e19]:
    - generic [ref=f1e20]:
      - generic [ref=f1e21]:
        - img "E2E Task 7 Hospital logo" [ref=f1e22]
        - paragraph [ref=f1e23]: E2E Task 7 Hospital
      - generic [ref=f1e25] [cursor=pointer]:
        - generic [ref=f1e26]: E
        - generic [ref=f1e28]:
          - paragraph [ref=f1e29]: E2E Doctor
          - paragraph [ref=f1e30]: doctor
    - generic [ref=f1e32]:
      - generic [ref=f1e33]:
        - generic [ref=f1e34]:
          - heading "Prescription Builder" [level=1] [ref=f1e35]
          - paragraph [ref=f1e36]: "Patient: E2E Patient"
        - button "Back" [ref=f1e37] [cursor=pointer]
      - generic [ref=f1e40]:
        - generic [ref=f1e41]:
          - generic [ref=f1e42]:
            - heading "Medicines" [level=2] [ref=f1e43]
            - button "Add Medicine" [ref=f1e44] [cursor=pointer]
          - paragraph [ref=f1e48]: No medicines added. Click "Add Medicine" to add.
        - generic [ref=f1e49]:
          - generic [ref=f1e50]:
            - heading "Lab Tests" [level=2] [ref=f1e51]
            - button "Add Test" [ref=f1e52] [cursor=pointer]
          - paragraph [ref=f1e55]: No lab tests added. Click "Add Test" to add.
        - generic [ref=f1e56]:
          - generic [ref=f1e57]: General Instructions
          - textbox "Diet, rest, follow-up instructions for the patient…" [ref=f1e58]
        - generic [ref=f1e59]:
          - button "Back" [ref=f1e60] [cursor=pointer]
          - button "Save Prescription" [ref=f1e61] [cursor=pointer]
```

# Test source

```ts
  1   | import { test, expect, type APIRequestContext, type Page } from '@playwright/test'
  2   | 
  3   | const doctor = {
  4   |   username: 'e2e_doctor_task7',
  5   |   password: 'E2eDoctor@123',
  6   |   visitId: 'a5a85a47-7a23-5587-97de-56daaf8b7822',
  7   | }
  8   | 
  9   | async function login(page: Page) {
  10  |   await page.goto('/login')
  11  |   await page.getByPlaceholder(/you@hospital\.in or mkrish66/i).fill(doctor.username)
  12  |   await page.locator('input[type="password"]').fill(doctor.password)
  13  |   await page.getByRole('button', { name: /sign in/i }).click()
  14  |   await expect(page).toHaveURL(/doctor/)
  15  | }
  16  | 
  17  | async function authRequest(request: APIRequestContext) {
  18  |   const response = await request.post('/api/v1/auth/login', { data: { login_id: doctor.username, password: doctor.password } })
  19  |   expect(response.ok()).toBeTruthy()
  20  |   const token = (await response.json()).access_token
  21  |   return { Authorization: `Bearer ${token}` }
  22  | }
  23  | 
  24  | test.describe.serial('Task 7 controlled clinical data', () => {
  25  |   test('doctor searches ICD-10 by code and description, selects, saves, and reloads diagnosis', async ({ page }) => {
  26  |     await login(page)
  27  |     await page.goto('/doctor/consultation')
  28  |     await page.getByRole('button', { name: /call in/i }).first().click()
  29  |     await page.getByRole('button', { name: /add diagnosis/i }).click()
  30  | 
  31  |     const diagnosis = page.getByPlaceholder(/search icd-10 code or description/i).first()
  32  |     await diagnosis.fill('J06')
  33  |     await expect(page.getByText(/E2E\.J06\.9/)).toBeVisible()
  34  |     await page.getByRole('button', { name: /E2E\.J06\.9/i }).click()
  35  |     await expect(diagnosis).toHaveValue(/E2E\.J06\.9.*E2E Acute upper respiratory infection/)
  36  | 
  37  |     await page.getByPlaceholder(/what brings the patient in today/i).fill('E2E cough follow-up')
  38  |     await page.getByRole('button', { name: /save & write prescription/i }).click()
  39  |     await expect(page).toHaveURL(/doctor\/prescription/)
  40  | 
  41  |     await page.goto('/doctor/consultation')
  42  |     await page.getByRole('button').filter({ hasText: 'E2E Patient' }).first().click()
  43  |     await expect(page.getByPlaceholder(/search icd-10 code or description/i).first()).toHaveValue(/E2E\.J06\.9.*E2E Acute upper respiratory infection/)
  44  |   })
  45  | 
  46  |   test('free-text diagnosis requires a reason and is visibly marked', async ({ page }) => {
  47  |     await login(page)
  48  |     await page.goto('/doctor/consultation')
  49  |     await page.getByRole('button').filter({ hasText: 'E2E Patient' }).first().click()
  50  |     await page.getByRole('button', { name: /free-text diagnosis/i }).first().click()
  51  |     await page.getByPlaceholder('Free-text diagnosis', { exact: true }).fill('E2E uncommon syndrome')
  52  |     await page.getByRole('button', { name: /save & write prescription/i }).click()
  53  |     await expect(page.getByPlaceholder(/reason for using free-text diagnosis/i)).toBeVisible()
  54  |     await page.getByPlaceholder(/reason for using free-text diagnosis/i).fill('No suitable ICD-10 code exists')
  55  |     await expect(page).toHaveURL(/doctor\/consultation/)
> 56  |     await page.locator('form').getByRole('button', { name: /save & write prescription/i }).click()
      |                                                                                            ^ Error: locator.click: Test timeout of 30000ms exceeded.
  57  |     await expect(page).toHaveURL(/doctor\/prescription/)
  58  |   })
  59  | 
  60  |   test('doctor searches distinct medicines, fills multiple rows, and reloads prescription details', async ({ page }) => {
  61  |     await login(page)
  62  |     await page.goto(`/doctor/prescription/${doctor.visitId}`)
  63  |     const medicineSearch = page.getByPlaceholder(/search generic, brand, strength or form/i).first()
  64  |     await page.getByRole('button', { name: /add medicine/i }).click()
  65  |     await medicineSearch.fill('E2E Paracetamol')
  66  |     await expect(page.getByText(/500 mg.*Tablet/)).toBeVisible()
  67  |     await page.getByRole('button', { name: /E2E Paracetamol.*500 mg.*Tablet/i }).click()
  68  |     await page.getByLabel(/dose/i).first().fill('1')
  69  |     await page.getByLabel(/duration/i).first().selectOption({ label: '5 days' })
  70  |     await page.getByLabel(/quantity/i).first().fill('5')
  71  |     await page.getByRole('button', { name: /add medicine/i }).click()
  72  |     const secondSearch = page.getByPlaceholder(/search generic, brand, strength or form/i).nth(1)
  73  |     await secondSearch.fill('E2E Crocin')
  74  |     await expect(page.getByText(/650 mg.*Capsule/)).toBeVisible()
  75  |     await page.getByRole('button', { name: /E2E Paracetamol.*650 mg.*Capsule/i }).click()
  76  |     await page.getByLabel(/dose/i).nth(1).fill('1')
  77  |     await page.getByLabel(/duration/i).nth(1).selectOption({ label: '3 days' })
  78  |     await page.getByLabel(/quantity/i).nth(1).fill('3')
  79  |     await page.getByRole('button', { name: /save prescription|complete/i }).click()
  80  |     await expect(page).toHaveURL(/doctor\/consultation/)
  81  | 
  82  |     await page.goto(`/doctor/prescription/${doctor.visitId}`)
  83  |     await expect(page.getByText(/E2E Paracetamol/).first()).toBeVisible()
  84  |     await expect(page.getByText(/500 mg/).first()).toBeVisible()
  85  |   })
  86  | 
  87  |   test('inactive medicine is absent and non-doctor access is rejected by real APIs', async ({ request }) => {
  88  |     const headers = await authRequest(request)
  89  |     const medicines = await request.get('/api/v1/master-data/medicines?q=inactive', { headers })
  90  |     expect(medicines.ok()).toBeTruthy()
  91  |     expect(await medicines.json()).toEqual([])
  92  | 
  93  |     const consultation = await request.post('/api/v1/consultations', {
  94  |       headers: { Authorization: headers.Authorization },
  95  |       data: { visit_id: doctor.visitId, chief_complaint: 'authorization check' },
  96  |     })
  97  |     expect([200, 201, 409]).toContain(consultation.status())
  98  |   })
  99  | })
  100 | 
```