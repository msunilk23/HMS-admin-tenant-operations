# HMS UAT READINESS AUDIT

**Date**: 2026-08-29  
**Audit Scope**: Lab + Billing UAT-critical functionality  
**Classification**: Read-only gap analysis (NO implementation changes)

---

## EXECUTIVE SUMMARY

### Current Status
- **P29 Migration**: ✅ FIXED & VALIDATED
- **Pharmacy P25-P29**: ✅ UAT READY (core functionality complete)
- **Lab Module**: ⚠️ PARTIALLY READY (P13 basic flow implemented; master data minimal)
- **Billing Module**: ✅ SUBSTANTIALLY READY (invoicing, payments, receipts, refunds complete)
- **OPD → Lab Integration**: ✅ IMPLEMENTED
- **OPD → Pharmacy Integration**: ✅ IMPLEMENTED  
- **Lab → Billing Integration**: ⚠️ PARTIAL (must define lab billing trigger)
- **Pharmacy → Billing Integration**: ✅ IMPLEMENTED

### UAT Readiness Classification
- **P0 UAT Blockers**: 3 items (must fix before UAT)
- **P1 Required Before UAT**: 4 items (operationally important)
- **P2 Post-UAT Polish**: 8 items (nice-to-have, not blocking)

### Estimated Work
- **P0 Fixes**: 2–3 hours (backend + frontend)
- **P1 Implementation**: 4–6 hours
- **P2 Polish**: Deferred post-UAT

---

## CURRENT UAT-READY MODULES

### Pharmacy P25-P29 ✅ COMPLETE
- Medicine Master (search, CRUD, pricing)
- Formulary (approval, prescribability)
- Procurement (PO, GRN, supplier management)
- Inventory (stock tracking, FIFO batches, adjustments)
- Dispensing (RESERVED → CONFIRMED → BILLING workflow)
- Billing (invoicing, cash/online payment, refunds, cancellations)
- Payment Integration (Razorpay + fallback sync)
- Audit Trail (transactional, immutable)
- RBAC (granular per-operation)
- Tenant Isolation (schema-based)

### OPD Core ✅ COMPLETE
- Patient registration
- Appointment / walk-in
- Nurse pre-vitals
- Doctor consultation
- Visit state machine
- Prescription creation
- Lab ordering
- Queue management
- Feedback

---

## LAB MODULE AUDIT

### Current Implementation Status

#### ✅ IMPLEMENTED — Core Lab Workflow (P13)
- **LabOrder model** (migration 0002)
  - Columns: id, visit_id, tests (JSONB), status, timestamps (ordered_at, sample_collected_at, processing_started_at, result_ready_at, verified_at, completed_at)
  - FK to visits (implicit visit patient/doctor linkage)
  - Status machine: ordered → sample_pending → sample_collected → processing → result_ready → verified → completed
  - Rejection path: rejected → sample_pending (recollection)
  - Indexes: visit_id

- **LabResult model** (migration 0002 + 0027)
  - Columns: id, lab_order_id, results (JSONB), notes, critical_flags (JSONB), report_url, reported_by_user_id, reported_at, verified_by_user_id, verified_at
  - FK to lab_orders
  - Cloudinary PDF/image report upload support

- **Backend Lab API** (`backend/app/api/v1/lab.py`)
  - POST /lab — create order (doctor/admin only)
  - GET /lab — list orders (doctor, nurse, lab tech, receptionist, admin)
  - PATCH /lab/{id}/status — advance status (nurse, doctor, lab tech, admin)
  - POST /lab/{id}/reject — reject sample (lab tech, admin)
  - POST /lab/{id}/results — enter results (nurse, doctor, lab tech, admin)
  - POST /lab/{id}/verify — verify results (lab tech, admin)
  - POST /lab/{id}/results/upload — upload PDF/image report (lab tech, admin)
  - GET /lab/{id}/results/report — download report (all staff)
  - GET /lab/{id}/results — read results (all staff)

- **Frontend Lab UI** (`frontend/src/features/lab/LabPage.tsx`)
  - Lab queue card display (ordered, sample_pending, sample_collected, processing, result_ready, verified, completed)
  - Status badge colors
  - Advance/reject buttons with state-aware flow
  - Result entry modal (per-test values, notes, file upload)
  - Rejection flow
  - Result verification
  - PDF report download (via signed Cloudinary URL)

- **WebSocket Integration**
  - lab:update broadcast on status changes
  - visit:update broadcast on results-ready (notifies doctor)

- **Audit Trail**
  - CREATE (lab order)
  - UPDATE (status transitions)
  - Record audit for all state changes

#### ⚠️ PARTIAL — Lab Master Data

| Item | Status | Notes |
|------|--------|-------|
| Test Master table | ❌ MISSING | No table for test code, name, department, pricing, reference range, etc. Currently tests stored as `{"test": "CBC", "notes": "..."}` in LabOrder.tests JSONB. |
| Test pricing | ❌ MISSING | No pricing model; billing must hardcode or accept lab test charges at invoice time. |
| Sample type master | ❌ MISSING | No sample type table; not tracked in LabOrder/LabResult. |
| Reference ranges | ❌ MISSING | No unit, reference range, gender/age-specific ranges defined. |
| Abnormal flag logic | ⚠️ PARTIAL | `LabResult.critical_flags` (JSONB) exists but no schema/validation defined. |
| Turnaround time | ❌ MISSING | Not tracked per test. |
| Department/category | ❌ MISSING | Lab tests not grouped by department (e.g., Biochemistry, Hematology, Microbiology). |

#### ⚠️ PARTIAL — Lab → Doctor Result Visibility

**Current Implementation**:
- GET /lab/{id}/results returns LabResultRead to authenticated staff (all roles can read)
- Frontend LabPage shows results in lab queue (but no doctor-specific view)
- WebSocket visit:update on result-ready notifies doctor (broadcast event only, no dedicated result display)

**Missing**:
- No dedicated Doctor Results Page showing patient's completed lab results
- No historical lab result archive per patient/visit
- Frontend doctor/consultation page does not display results inline

#### ✅ WORKING — Doctor → Lab Order Flow

| Item | Implementation |
|------|---|
| Doctor writes Rx | ✅ Existing POST /consultations creates prescription (consultation endpoint populates prescription_items) |
| Test selection | ✅ POST /lab creates order with tests list: `[{test: "CBC", notes: "fasting"}]` |
| Lab queue | ✅ GET /lab filters by status; lab tech sees ordered tests |
| Multiple tests | ✅ payload.tests is a list; POST /lab accepts `LabOrderCreate(visit_id, tests=[...])` |
| Sample collection | ✅ PATCH /lab/{id}/status → sample_pending → sample_collected |
| Result entry | ✅ POST /lab/{id}/results enters results, transitions to result_ready |
| Verification | ✅ POST /lab/{id}/verify marks verified |
| Doctor visibility | ⚠️ PARTIAL — no dedicated UI; only WebSocket notification |

#### ❌ NOT IMPLEMENTED — Lab Billing Linkage

| Requirement | Status | Implementation |
|---|---|---|
| Billing trigger | ❌ MISSING | Unclear whether billing occurs at test order, sample collection, result entry, or verification. No FK from Invoice to LabOrder/LabResult. |
| Lab charge line item | ❌ MISSING | Invoices accept generic line items `{description, amount}`; no reference to lab test. |
| Duplicate billing prevention | ❌ MISSING | No idempotency guard if billing process retries. |
| Lab payment routing | ❌ MISSING | Invoices can have multiple sources (consultation, pharmacy, lab, combined); no current routing logic for lab-only bills. |

---

## BILLING MODULE AUDIT

### ✅ IMPLEMENTED — Core Billing Workflow

#### Invoice Lifecycle
- **States**: draft → pending → partially_paid → paid → refunded/cancelled
- **Properties**: id, visit_id, line_items (JSONB), subtotal, discount, tax, total, paid_amount, payment_method, status, razorpay_order_id, razorpay_payment_id, receipt_number, pharmacy_dispense_id (nullable FK for P29 linkage)
- **Audit Trail**: CREATE, UPDATE, REFUND, CANCEL actions with full context

#### Line Items
- Generic structure: `{description, amount}`
- Supported sources: consultation_fee, lab_charges, pharmacy_dispense, other

#### Payment Methods
| Method | Implementation |
|--------|---|
| Cash | ✅ IMPLEMENTED — POST /billing/{id}/pay with payment_method="cash" |
| Razorpay Online | ✅ IMPLEMENTED — creates order via create_razorpay_order(), webhook handler processes payment.captured/payment.authorized |
| UPI | ✅ IMPLEMENTED — same Razorpay flow, method="upi" |
| Card | ✅ IMPLEMENTED — same Razorpay flow, method="card" |
| Netbanking | ✅ IMPLEMENTED — same Razorpay flow, method="netbanking" |
| Insurance | ⚠️ PARTIAL — schema accepts; no payment gateway integration |
| Credit | ❌ NOT IMPLEMENTED — deferred by P29 approval (no HMS credit auth mechanism exists) |

#### Payment Processing
- **Razorpay Order Creation**: create_razorpay_order() returns order with id and amount_paise
- **Webhook Handler**: razorpay_webhook() verifies HMAC-SHA256 signature, processes payment.captured/payment.authorized events
- **Fallback Sync**: POST /billing/{id}/sync-payment calls Razorpay API to fetch order payments if webhook missed
- **Concurrency**: Payment idempotency via Invoice.razorpay_order_id uniqueness + Razorpay's idempotent order API
- **Transactional**: Payment recorded in same DB transaction as invoice.status update

#### Receipt Generation
- ✅ Invoice.receipt_number auto-generated: `RCT-{YYYYMMDD}-{INVOICEID[:8]}`
- ✅ GET /billing/{id}/receipt returns paid invoice (200 only if status in (paid, refunded))
- ⚠️ No PDF receipt generation; must finalize document via POST /billing/{id}/documents/finalize
- ⚠️ Cloudinary-hosted PDF but no configured email delivery

#### Refunds & Cancellations
- **Refund** (paid invoices): POST /billing/{id}/refund → status=refunded, paid_amount→0, Refund record created
- **Cancellation** (unpaid invoices): POST /billing/{id}/cancel → status=cancelled, releases linked pharmacy reservation
- ✅ Full-amount refunds only (design choice; partial refunds deferred)
- ✅ Reason tracking for both

#### Document Management
- **Invoice PDF Finalization**: POST /billing/{id}/documents/finalize → generates PDF via invoice_pdf_service.build_invoice_pdf(), stores versioned copy via DocumentVersion table
- **Multiple Versions**: invoices can have multiple PDF versions (re-finalization idempotent via snapshot_checksum)
- **Download**: GET /billing/{id}/documents/{version}/download

#### Pharmacy Billing Integration (P29)
- ✅ Invoice.pharmacy_dispense_id FK to PharmacyDispense
- ✅ Unique constraint uq_invoices_pharmacy_dispense (one invoice per dispense)
- ✅ Invoice source="pharmacy_dispense" flag
- ✅ Payment authorization triggers PharmacyDispense billing_status="AUTHORIZED"
- ✅ Cancellation releases PharmacyDispense reservations

### ⚠️ PARTIAL — Unified Patient Billing

| Item | Status | Notes |
|------|--------|-------|
| Consolidated invoice | ⚠️ PARTIAL | Invoice table can hold multiple line items; but current POST /billing endpoint creates one invoice per visit. No multi-visit/multi-service consolidation. |
| Service-specific invoices | ✅ WORKING | Separate invoices for consultation (source="consultation") vs pharmacy (source="pharmacy_dispense") can be created; no automatic consolidation. |
| Lab charges | ❌ MISSING | No billing trigger defined for lab orders; no automatic line item insertion. |

### ✅ WORKING — Billing RBAC

| Permission | Implementation |
|---|---|
| Invoice view | ✅ require_role("receptionist", "billing_officer", "nurse", "doctor", "hospital_admin") |
| Invoice create | ✅ require_role("receptionist", "billing_officer", "hospital_admin") |
| Payment recording | ✅ require_role("receptionist", "billing_officer", "hospital_admin") |
| Refund | ✅ require_role("billing_officer", "hospital_admin") |
| Cancellation | ✅ require_role("billing_officer", "hospital_admin") |
| Pharmacy payment | ✅ require_permission("PHARMACY_BILLING_PAYMENT") — granular role-based |
| Pharmacy refund | ✅ require_permission("PHARMACY_BILLING_REFUND") |
| Pharmacy cancellation | ✅ require_permission("PHARMACY_BILLING_CANCEL") |

### ✅ IMPLEMENTED — Billing Idempotency

| Scenario | Protection |
|---|---|
| Duplicate payment webhook | ✅ Invoice.razorpay_payment_id prevents double-payment (unique + check if status already paid) |
| Duplicate payment callback | ✅ Payment table design supports multiple payments per invoice; duplicate detection via transaction_reference unique constraint |
| Browser reload after payment | ✅ Invoice status persists; frontend must check status before allowing re-payment |
| Retry of payment sync | ✅ POST /sync-payment idempotent (returns existing paid invoice if already paid) |
| Multiple POS display boards | ✅ Razorpay order_id unique per invoice; only one board can capture (design assumes order → one real payment) |

### ✅ IMPLEMENTED — Billing Audit

| Event | Audit |
|---|---|
| Invoice creation | ✅ record_audit(CREATE, resource_type=invoice, new_value={line_items, subtotal, tax, total, status}) |
| Status transition | ✅ record_audit(UPDATE, old_value/new_value) |
| Payment recording | ✅ record_audit(CREATE, resource_type=payment, new_value={invoice_id, amount, method, status}) |
| Refund | ✅ record_audit(REFUND, old_value={status: paid}, new_value={status: refunded}, reason) |
| Cancellation | ✅ record_audit(CANCEL, reason) |
| Pharmacy-specific | ✅ PHARMACY_PAYMENT_INITIATED, PHARMACY_PAYMENT_COMPLETED, PHARMACY_BILLING_CANCELLED |

---

## OPD → LAB INTEGRATION

### ✅ IMPLEMENTED Doctor Lab Ordering

```
Doctor Consultation
  → POST /consultations with chief_complaint/diagnosis
  → Consultation.id created
  → Doctor can POST /lab with visit_id + tests=[{test, notes}]
  → LabOrder.id created, linked to Visit.id
  → Lab tech sees order in GET /lab (status=ordered)
  → Lab flow: sample → processing → result → verify → complete
```

**Integration Points**:
- ✅ Doctor role can create lab orders (require_role("doctor", "hospital_admin"))
- ✅ Lab order linked to visit via FK
- ✅ Lab order linked to patient via visit.patient_id
- ✅ Visit lifecycle independent (lab doesn't drive visit state)
- ✅ WebSocket lab:update notifies staff
- ✅ WebSocket visit:update notifies when results ready (doctor aware via broadcast)

### ⚠️ PARTIAL Doctor Result Visibility

**Current**:
- ✅ Results stored in LabResult (results JSONB)
- ✅ API endpoint GET /lab/{id}/results exists
- ✅ WebSocket visit:update event "lab_results_ready" broadcasts when LabOrder.status=result_ready
- ✅ LabPage frontend shows results in lab queue

**Missing**:
- ❌ Doctor-specific UI page showing "Results for My Patients"
- ❌ Consultation page doesn't inline lab results
- ❌ Historical archive of lab results per patient
- ❌ Result notification mechanism (SMS/email) to doctor

---

## OPD → PHARMACY INTEGRATION

### ✅ FULLY IMPLEMENTED

**Flow**:
```
Doctor Rx
  → Prescription.id created
  → Prescription_items populated
  → POST /pharmacy/dispense auto-creates PharmacyDispense
  → Pharmacy queue updated
  → Pharmacist fulfills (internal/outside)
  → PharmacyDispense.status → CONFIRMED
  → PharmacyDispense.billing_status → AUTHORIZED (if invoice paid)
  → Stock deducted (one-time, idempotent)
  → Receipt issued
```

**Verified in P29 Tests**: 9/9 tests pass  
**Audit Trail**: Complete (CREATE, UPDATE, CONFIRM, CANCEL, PAYMENT_* actions)  
**Tenant Isolation**: ✅ Verified  
**Concurrency**: ✅ Row-locked, no duplicates  
**Idempotency**: ✅ All operations safe to retry

---

## LAB → BILLING INTEGRATION

### ❌ NOT IMPLEMENTED — Missing Lab Billing Trigger

**Problem**: No automatic billing when lab order is completed.

| Component | Status | Details |
|---|---|---|
| Lab Test Master | ❌ MISSING | No test table with pricing; tests stored as JSONB strings in LabOrder.tests |
| Billing Trigger | ❌ UNDEFINED | When should billing occur? Options: (1) at order creation, (2) at result verification, (3) manual clerk action |
| Charge Amount | ❌ UNDEFINED | Fixed price? Volume discount? Negotiated? Hardcoded in code? Master data? |
| Invoice Line Item | ❌ MISSING | No automatic invoice line item creation for lab charges. Manual billing only. |
| Lab Test Linkage | ❌ MISSING | No FK from Invoice to LabOrder/LabResult; no reference in invoice.line_items. |
| Duplicate Prevention | ❌ MISSING | If clerk creates invoice + lab charges twice, no idempotency guard. |

### ⚠️ DECISION REQUIRED FOR UAT

**Option A** (Simple): No automatic lab billing; clerk manually creates invoice with lab line items
- **Pros**: Minimal code change; works for first UAT if volumes low
- **Cons**: Error-prone; requires clerk discipline; audit trail shows manual entry, not system-driven

**Option B** (Better): Create Lab Test Master + auto-billing on verification
- **Pros**: Clean audit; idempotent; scales
- **Cons**: 4–6 hours to implement (model, migration, API, billing trigger)

**Recommendation for UAT**: Option A + document as P1 (fix before production)

---

## PHARMACY → BILLING INTEGRATION

### ✅ FULLY IMPLEMENTED (P29)

**Flow**:
```
PharmacyDispense
  → POST /pharmacy/dispense/{id}/bill
  → Creates Invoice (source="pharmacy_dispense")
  → Links Invoice.pharmacy_dispense_id
  → Sets line_items from dispense items
  → POST /billing/{id}/pay
  → Payment recorded
  → Webhook verifies Razorpay capture
  → Pharmacy dispense billing_status → AUTHORIZED
  → Stock deducted atomically
```

**Verified in P29 Tests**: All pharmacy + billing tests pass  
**Unique Constraint**: uq_invoices_pharmacy_dispense (one bill per dispense)  
**Idempotency**: ✅ Full (re-payment sync, duplicate detection)  
**Audit**: ✅ Complete (PAYMENT_INITIATED, PAYMENT_COMPLETED, AUTHORIZED)

---

## PAYMENT INTEGRATION

### ✅ IMPLEMENTED — Razorpay

| Component | Status |
|---|---|
| Order creation | ✅ create_razorpay_order(amount_rupees, receipt, notes) |
| Key/secret auth | ✅ Via settings.RAZORPAY_KEY_ID/.RAZORPAY_KEY_SECRET |
| Webhook HMAC verification | ✅ verify_webhook_signature(body, X-Razorpay-Signature header) |
| Event handling | ✅ payment.captured / payment.authorized |
| Tenant routing | ✅ Tenant schema embedded in order notes; webhook extracts and routes |
| Payment verification | ✅ fetch_order_payments() fallback if webhook missed |
| Auto-capture | ✅ payment_capture=True on order creation |
| Amount validation | ✅ Razorpay paise conversion + order amount matches invoice total |

### ✅ IMPLEMENTED — Cash

| Component | Status |
|---|---|
| Nurse admission flow | ✅ POST /billing/{id}/admit-patient (receptionist marks paid in cash) |
| Manual recording | ✅ POST /billing/{id}/payments (billing officer records cash payment) |
| Receipt generation | ✅ Auto-number RCT-{YYYYMMDD}-{ID} |
| Audit | ✅ Recorded as payment_method="cash" |

### ❌ NOT IMPLEMENTED — Insurance

**Schema exists** (invoice.payment_method accepts "insurance") but no integration with insurance provider APIs, pre-auth, claim submission, or EOB processing.

**For UAT**: Insurance payments can be manually recorded via POST /billing/{id}/payments with payment_method="insurance" + notes describing claim/auth. Not required for first UAT.

---

## RBAC AUDIT

### ✅ Lab RBAC

| Permission | Role | Implementation |
|---|---|---|
| Create lab order | doctor, hospital_admin | require_role("doctor", "hospital_admin") |
| View lab orders | nurse, doctor, lab_technician, receptionist, hospital_admin | require_role(...) |
| Advance status | nurse, doctor, lab_technician, hospital_admin | require_role(...) |
| Reject sample | lab_technician, hospital_admin | require_role(...) |
| Enter results | nurse, doctor, lab_technician, hospital_admin | require_role(...) |
| Verify results | lab_technician, hospital_admin | require_role(...) |
| Upload report | lab_technician, hospital_admin | require_role(...) |
| Read results | all staff | require_role(...) |

### ✅ Billing RBAC

| Permission | Role | Implementation |
|---|---|---|
| View invoices | receptionist, billing_officer, hospital_admin, nurse, doctor | require_role(...) |
| Create invoices | receptionist, billing_officer, hospital_admin | require_role(...) |
| Record payment | receptionist, billing_officer, hospital_admin | require_role(...) |
| Issue refund | billing_officer, hospital_admin | require_role(...) |
| Cancel invoice | billing_officer, hospital_admin | require_role(...) |
| Pharmacy payment (granular) | require_permission("PHARMACY_BILLING_PAYMENT") | ✅ Implemented via permission model |
| Pharmacy cancel (granular) | require_permission("PHARMACY_BILLING_CANCEL") | ✅ Implemented |

---

## TENANT / FACILITY ISOLATION

### ✅ Lab — Tenant Isolation

- LabOrder / LabResult tables in tenant schemas (search_path per request)
- No tenant_id column needed (schema enforces)
- Audit trail implicit (tenant context via middleware)
- WebSocket broadcasts per-tenant (tenant_schema from JWT)

### ✅ Billing — Tenant Isolation

- Invoice / Payment / Refund tables in tenant schemas
- Pharmacy dispense billing properly scoped
- Razorpay order notes carry tenant_schema; webhook routes correctly
- No cross-tenant invoice creation possible (schema isolation)

### ⚠️ Facility Isolation — Partial

- Pharmacy inventory scoped per facility (PharmacyLocation.facility_id)
- Lab orders NOT explicitly scoped to facility (design assumes one facility per tenant for first UAT)
- **For multi-facility UAT**: Add facility_id to LabOrder, filter GET /lab by facility

---

## AUDIT TRAIL AUDIT

### ✅ Lab Audit

| Event | Tracked | Details |
|---|---|---|
| Lab order creation | ✅ | action=CREATE, resource_type=lab_order, new_value={status, tests} |
| Status transition | ✅ | action=UPDATE, old_value={status}, new_value={status} |
| Sample rejection | ✅ | action=UPDATE (from lab.py update_lab_order_status) |
| Result entry | ✅ | action=CREATE, resource_type=lab_result, new_value={results, notes} |
| Result verification | ✅ | action=UPDATE, resource_type=lab_result, verified_by_user_id tracked |

**Gaps**:
- ❌ No patient_id linkage in lab audits (audit_service.record_audit accepts patient_id but not passed from lab.py)

### ✅ Billing Audit

| Event | Tracked | Details |
|---|---|---|
| Invoice creation | ✅ | Full line_items, amounts, status |
| Payment recording | ✅ | amount, method, razorpay reference |
| Status transition | ✅ | draft → pending → paid, etc. |
| Refund | ✅ | Refund.reason captured |
| Cancellation | ✅ | Cancellation.reason captured |
| Pharmacy-specific | ✅ | PHARMACY_PAYMENT_INITIATED, COMPLETED, AUTHORIZED, CANCELLED |

**Quality**: Excellent; all financial operations fully audited

---

## AUTOMATED TEST COVERAGE

### Lab Tests

| Test File | Tests | Coverage |
|---|---|---|
| test_lab_workflow_phase13.py | 8 | Status transitions (ordered → completed, rejected → sample_pending) |
| test_lab_*_phase13.py | (assumed) | Lab queue operations, result entry, verification |

**Gap**: No database-backed concurrency tests; no duplicate result prevention; no orphaned lab order cleanup

### Billing Tests

| Test File | Tests | Coverage |
|---|---|---|
| test_billing_phase14.py | 6 | Invoice creation, payment, receipt |
| test_pharmacy_billing_linkage_phase29.py | 2 | FK linkage, concurrent dispense insert |
| test_audit_phase16.py | 4 | Audit trail, sensitive data redaction |

**Coverage**: Solid for P29 pharmacy + OPD consultation billing; lab billing not tested

---

## P0 UAT BLOCKERS

### 1. ❌ Lab Test Master Missing

**Impact**: Cannot bill for lab tests; no pricing; cannot search tests.  
**Current State**: Tests stored as JSONB strings in LabOrder.tests (e.g., `{test: "CBC", notes: "fasting"}`).  
**Required for UAT**: Minimum lab test catalog (code, name, price).

**Recommended Fix**:
- Create `lab_test_master` table (id, code, name, description, price, is_active)
- Add migration
- Create /api/v1/master-data/lab-tests endpoint (reuse existing master-data pattern from medicine/dosage-form)
- Update LabOrderCreate schema to accept test_id instead of free-text

**Effort**: 2–3 hours  
**P0 Priority**: HIGH (cannot bill without test master)

### 2. ❌ Lab → Billing Trigger Undefined

**Impact**: Lab orders are created but never billed; manual clerk workaround required.  
**Current State**: No automatic invoice creation when lab completes.

**Recommended Fix** (Decision Required):
- **Option A**: Manual billing (clerk creates invoice with lab line items) — 30 min docs only
- **Option B**: Auto-billing on verification (POST /lab/{id}/verify triggers invoice creation) — 2 hours implementation

**For First UAT**: Option A is acceptable IF volumes low; document as known limitation.

**P0 Priority**: MEDIUM (UAT can proceed with manual billing if documented)

### 3. ⚠️ Doctor Lab Results UI Missing

**Impact**: Doctor cannot view lab results in consultation workflow; only via broadcast notification.  
**Current State**: Results stored in database; GET /lab endpoint exists; no doctor-specific UI page.

**Recommended Fix**:
- Create "Lab Results" tab in ConsultationPage or separate page
- Query GET /lab/{id}/results for each patient visit
- Display results in table format

**Effort**: 2–3 hours frontend  
**P0 Priority**: MEDIUM (blocks doctor UAT experience; not a data correctness issue)

---

## P1 REQUIRED BEFORE UAT

### 1. Lab Patient_id Audit Linkage

**Current**: Lab audits don't include patient_id even though LabOrder.visit_id→visit.patient_id.  
**Fix**: Pass patient_id to record_audit() in lab.py endpoints.  
**Effort**: 30 minutes  
**Impact**: Audit compliance; easier forensics

### 2. Lab Facility Scoping

**Current**: Lab orders not scoped to facility (assumes single facility per tenant).  
**Fix**: Add facility_id to LabOrder model + migration; filter GET /lab by facility context.  
**Effort**: 1–2 hours  
**Impact**: Multi-facility UAT; optional for first UAT if single facility only

### 3. Lab Concurrency Tests

**Current**: No database-backed tests for concurrent result entry, verification, sample rejection.  
**Fix**: Add concurrency tests similar to pharmacy_billing_linkage tests (parallel result entry, verify immutability).  
**Effort**: 1–2 hours  
**Impact**: Safety validation; not strictly blocking

### 4. Billing Payment Retry Validation

**Current**: Payment retry logic is present (sync-payment) but no automated test for webhook failure recovery.  
**Fix**: Add test: webhook-missed → payment-sync → invoice marked paid.  
**Effort**: 1 hour  
**Impact**: Confidence in payment resilience

---

## P2 POST-UAT POLISH

1. Lab Test Reference Ranges (age/gender-specific normal values)
2. Lab Result Critical Flags (automatic abnormal detection)
3. Lab Turnaround Time SLA Tracking
4. Insurance Payment Pre-auth Integration
5. Lab PDF Report with Normalization
6. Multi-service Consolidated Invoice (lab + consultation + pharmacy in one bill)
7. Doctor SMS/Email notification of lab results
8. Billing Dashboard & Financial Reports

---

## RECOMMENDED IMPLEMENTATION SEQUENCE

### Before UAT Opens (Estimated 5–7 hours)

**Phase 1 — P0 Lab Test Master** (2–3 hours)
1. Create lab_test_master migration (0077)
2. Add Lab Test Master model
3. Add API endpoints (CRUD, search)
4. Update LabOrderCreate schema
5. Update frontend to select tests from dropdown

**Phase 2 — Lab → Billing Trigger** (0.5–2 hours, decision-dependent)
- **Option A** (30 min): Document manual billing requirement in UAT guide
- **Option B** (2 hours): Implement auto-billing on verification

**Phase 3 — Doctor Lab Results UI** (2–3 hours)
1. Add Lab Results page or ConsultationPage tab
2. Query lab orders/results for visit
3. Display with sorting/filtering

**Phase 4 — P1 Quick Wins** (1–2 hours)
- Add patient_id to lab audits
- Add lab facility scoping
- Add concurrency tests

### After UAT Launch (Optional Deferred)

- Advanced master data (reference ranges, critical flags)
- Insurance integration
- Reporting & analytics
- Multi-service billing consolidation

---

## FINAL CLASSIFICATION

### P0 Blockers (Must Fix Before UAT)
1. Lab test master + API (2–3 hours)
2. Lab → billing trigger decision (0.5–2 hours)
3. Doctor lab results UI (2–3 hours)

**Subtotal**: 4.5–8 hours (realistic estimate: 6–7 hours with testing)

### P1 Items (Required, Medium Effort)
1. Lab patient_id audit linkage (0.5 hours)
2. Lab facility scoping (1–2 hours)
3. Lab concurrency tests (1–2 hours)
4. Payment retry validation test (1 hour)

**Subtotal**: 3.5–5.5 hours (realistic: 4–5 hours)

### P2 Items (Post-UAT Nice-to-Have)
1. Lab reference ranges
2. Lab critical flags
3. Lab SLA tracking
4. Insurance pre-auth
5. Lab PDF reports
6. Consolidated billing
7. Notifications
8. Dashboards

**Subtotal**: Deferred post-UAT

---

## SUMMARY TABLE

| Module | Current Status | UAT-Ready | Blockers | Effort |
|--------|---|---|---|---|
| Pharmacy P25-P29 | ✅ Complete | ✅ YES | None | — |
| OPD Core | ✅ Complete | ✅ YES | None | — |
| Lab Workflow | ✅ Partial | ⚠️ WITH FIXES | 3 P0 | 6–7h |
| Billing Core | ✅ Substantial | ✅ YES | None (lab triggers deferred) | — |
| Doctor Results | ⚠️ Backend only | ❌ NO | Need UI | 2–3h |
| Lab Master Data | ❌ Missing | ❌ NO | Test master needed | 2–3h |
| Lab → Billing | ❌ Undefined | ⚠️ MANUAL OK | Need decision | 0.5–2h |
| **TOTAL** | | | **3 P0, 4 P1** | **9–12h** |

---

## AUDIT CONCLUSION

### HMS is **SUBSTANTIALLY READY** for Lab + Billing UAT with caveats:

**Go-Live Options**:

**Option 1 — Conservative (Full Readiness)**
- Fix all 3 P0 blockers + all 4 P1 items
- Effort: 9–12 hours
- Risk: Very low
- Recommended for first UAT

**Option 2 — Pragmatic (Partial Readiness)**
- Fix P0 Lab Master + Lab UI only
- Manual billing for lab charges (document as known limitation)
- Defer facility scoping to multi-facility phase
- Effort: 4–5 hours
- Risk: Moderate (manual billing error-prone; no P1 safety nets)
- Acceptable if UAT volume is low and timeline is tight

---

## NEXT STEPS

### Awaiting User Approval

**Decision 1**: Fix all P0 + P1 (Conservative), or P0 only + manual billing (Pragmatic)?

**Decision 2**: If fixing Lab → Billing, choose Option A (manual, documented) or Option B (auto-billing)?

**Decision 3**: Is single-facility assumption acceptable for first UAT, or implement facility scoping now?

---

**Report Complete**

P0 Blockers: **3**  
P1 Items: **4**  
P2 Deferred: **8**  
Estimated P0+P1 Implementation: **9–12 hours**  
Estimated P0-Only Implementation: **4–5 hours**

**WAITING FOR USER APPROVAL:**

- **APPROVED - IMPLEMENT HMS P0 UAT BLOCKERS** (full 9–12 hour path)
- **APPROVED - IMPLEMENT HMS P0 + MANUAL BILLING** (pragmatic 4–5 hour path)

