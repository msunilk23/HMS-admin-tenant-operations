# HMS Core Stabilization Plan

## Objective

Stabilize the multi-tenant OPD foundation before extending HMS into IP, ER, OT, ICU and Smart Hospital capabilities.

The implementation agent must read:

`.github/copilot-instructions.md`

before working on any phase.

Only the explicitly assigned phase may be implemented.

---

# Phase Status

| Phase | Scope                                 | Status   |
| ----- | ------------------------------------- | -------- |
| 0     | Baseline / Regression Protection      | COMPLETE |
| 1     | Multi-Tenant Security                 | COMPLETE |
| 2     | Password / First Login Security       | COMPLETE |
| 3     | Canonical OPD State Machine           | COMPLETE |
| 4     | Visit as Encounter Backbone           | COMPLETE |
| 5     | Reception / Register Visit            | COMPLETE |
| 6     | Patient Registration Enhancements     | COMPLETE |
| 7     | Nurse Queue                           | COMPLETE |
| 8     | Complete Pre-Vitals                   | COMPLETE |
| 9     | Doctor Queue                          | COMPLETE |
| 10    | Consultation                          | COMPLETE |
| 11    | Structured Prescription               | COMPLETE |
| 12    | Pharmacy Workflow                     | COMPLETE |
| 13    | Lab Workflow                          | COMPLETE |
| 14    | Billing Workflow                      | COMPLETE |
| 15    | Queue / Real-Time Events              | COMPLETE |
| 16    | Audit Framework                       | COMPLETE |
| 17    | RBAC Enforcement                      | COMPLETE |
| 18    | Tenant Feature Enforcement            | COMPLETE |
| 19    | Nurse Roster                          | COMPLETE |
| 20    | TAT / Operational Timing              | COMPLETE |
| 21    | Feedback                              | COMPLETE |
| 22    | Automated Test Expansion              | COMPLETE |
| 23    | Frontend UX Alignment                 | COMPLETE |
| 24    | Documentation / Stabilization Release | PENDING  |

---

# Phase 0 — Baseline

Objective:

Establish build/run/test baseline.

Acceptance:

* backend starts
* frontend starts
* PostgreSQL works
* Redis works
* migrations succeed
* baseline tests established

---

# Phase 1 — Multi-Tenant Security

Objective:

Ensure one hospital can never access another hospital's data.

Requirements:

* JWT tenant authoritative
* client tenant override prohibited
* Super Admin uses dedicated APIs
* inactive/invalid tenants rejected
* cross-tenant regression tests

---

# Phase 2 — Password Security

Requirements:

* must_change_password
* password_changed_at
* first-login enforcement
* password-reset enforcement
* frontend route protection
* regression tests

---

# Phase 3 — Canonical OPD State Machine

Canonical states:

REGISTERED
→ WAITING_FOR_NURSE
→ IN_PRE_VITAL
→ WAITING_FOR_DOCTOR
→ IN_CONSULTATION
→ CONSULTATION_COMPLETED
→ CLOSED

Additional:

CANCELLED

Requirements:

* VisitWorkflowService authoritative
* no uncontrolled status writes
* invalid transitions rejected
* Pharmacy/Lab/Billing separated

---

# Phase 4 — Visit Backbone

Objective:

Make `visit_id` the encounter identity.

Ensure direct encounter linkage for:

* QueueToken
* Vitals
* Consultation
* Prescription
* LabOrder
* Invoice
* Feedback

New workflows must not depend on patient + date to identify encounters.

---

# Phase 5 — Reception / Register Visit

## Walk-In

Search/Register Patient
→ Select Department
→ Select Doctor
→ Create Visit
→ Queue Token
→ WAITING_FOR_NURSE

## Appointment

Find Appointment
→ Check-In
→ Create linked Visit
→ Queue Token
→ WAITING_FOR_NURSE

---

# Phase 6 — Patient Registration Enhancements

Implement/review:

* UHID generation
* patient create
* patient update
* patient search
* mobile search
* UHID search
* name search
* Aadhaar search where applicable
* DOB
* age
* gender
* address
* emergency contact
* blood group
* insurance
* active/inactive state
* duplicate detection
* authorized duplicate override
* patient change audit

Avoid storing derived information inconsistently where it can be calculated safely.

---

# Phase 7 — Nurse Queue

Implement:

WAITING_FOR_NURSE
→ Call Patient
→ Start Pre-Vitals
→ IN_PRE_VITAL

Requirements:

* department/assignment filtering
* nurse identity
* timestamps
* queue events
* authorization
* audit

---

# Phase 8 — Complete Pre-Vitals

Minimum clinical observations:

* temperature
* pulse
* respiratory rate
* systolic BP
* diastolic BP
* SpO2
* pain score
* height
* weight
* calculated BMI
* glucose
* chief complaint
* allergies
* Known No Allergies
* general condition
* level of consciousness
* nurse notes

Support:

* draft
* validation
* completion

Completion:

IN_PRE_VITAL
→ WAITING_FOR_DOCTOR

---

# Phase 9 — Doctor Queue

Requirements:

* doctor-specific queue
* permitted department
* Call Patient
* Open Consultation
* pre-vitals validation

Transition:

WAITING_FOR_DOCTOR
→ IN_CONSULTATION

Capture operational timestamps.

---

# Phase 10 — Consultation

Support:

* Draft
* In Progress
* Completed
* controlled Amendment

Clinical content:

* chief complaint
* HPI
* medical history
* examination
* provisional diagnosis
* final diagnosis
* ICD-10
* advice
* notes
* follow-up

Completion:

IN_CONSULTATION
→ CONSULTATION_COMPLETED

---

# Phase 11 — Prescription

Implement structured:

Prescription
+
PrescriptionItems

Items include:

* medicine
* strength
* dose
* route
* frequency
* duration
* quantity
* instructions

Maintain Visit and Consultation linkage.

---

# Phase 12 — Pharmacy

Independent states:

PENDING
→ CALLED
→ DISPENSING
→ DISPENSED

Also consider:

* PARTIALLY_DISPENSED
* OUT_OF_STOCK
* CANCELLED

Do not alter OPD Visit status to represent Pharmacy progress.

---

# Phase 13 — Lab

Independent lifecycle:

ORDERED
→ SAMPLE_PENDING
→ SAMPLE_COLLECTED
→ PROCESSING
→ RESULT_READY
→ VERIFIED
→ COMPLETED

Maintain Visit and Consultation linkage.

---

# Phase 14 — Billing

Support:

* registration
* consultation
* lab
* procedures
* pharmacy
* discount
* taxes/configuration
* payment
* receipts
* refunds
* supported online payment

States:

DRAFT
PENDING
PARTIALLY_PAID
PAID
CANCELLED
REFUNDED

Payment webhooks must be signature verified and tenant safe.

---

# Phase 15 — Real-Time Events

Review Redis/WebSocket integration.

Events should include:

* visit registration
* queue update
* nurse call
* pre-vitals start
* pre-vitals complete
* doctor call
* consultation start
* consultation complete
* Pharmacy
* Lab
* Billing

PostgreSQL remains authoritative.

---

# Phase 16 — Audit

Complete audit infrastructure.

Prioritize:

* patient
* visit
* clinical documentation
* prescriptions
* dispensing
* lab
* billing
* discounts/refunds
* users/roles
* tenants/features

---

# Phase 17 — RBAC

Backend enforce:

* receptionist
* nurse
* doctor
* pharmacist
* lab
* billing
* hospital_admin
* super_admin

Test forbidden cross-role operations.

---

# Phase 18 — Tenant Features

Feature controls must work at:

* API
* frontend route
* frontend navigation

Backend remains authoritative.

---

# Phase 19 — Nurse Roster

Support:

* date
* shift
* nurse
* department
* room
* doctor
* attendance
* substitution

Prepare for future workload/utilization analysis.

---

# Phase 20 — TAT Instrumentation

Capture reliable timestamps for:

Registration
→ Nurse
→ Pre-Vitals
→ Doctor
→ Consultation
→ Lab
→ Pharmacy
→ Billing

Calculate operational waiting and service durations.

Do not add predictive AI yet.

---

# Phase 21 — Feedback

Implement:

* visit-linked feedback
* rating
* comments
* channel
* submitted timestamp

Prepare architecture for QR/SMS/WhatsApp/kiosk and escalation.

---

# Phase 22 — Automated Tests

Expand comprehensive tests covering:

* authentication
* tenant isolation
* RBAC
* patients
* appointments
* visits
* queue
* nurse
* doctor
* consultation
* prescription
* Pharmacy
* Lab
* Billing
* payment
* audit

Include negative and concurrency scenarios where appropriate.

---

# Phase 23 — Frontend UX Alignment

Ensure coherent screens for:

* Reception Dashboard
* Register Visit
* Patients
* Appointments
* Queue
* Nurse Queue
* Pre-Vitals
* Doctor Queue
* Consultation
* Pharmacy
* Lab
* Billing
* Staff
* Roster
* Tenant Admin
* Super Admin

Backend contracts remain authoritative.

---

# Phase 24 — Stabilization Release

Generate/update:

* OPD workflow
* API documentation
* data model
* state diagrams
* RBAC matrix
* tenant architecture
* deployment documentation

Run:

* backend regression suite
* frontend type-check
* frontend production build
* migration test
* Docker deployment test

Target release:

**HMS OPD Core v1**
