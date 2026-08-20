# HMS — GitHub Copilot Permanent Development Instructions

## 1. Purpose

This repository contains a multi-tenant Hospital Management System (HMS).

The immediate objective is to stabilize the OPD foundation before extending the platform into IP, ER, OT, ICU, advanced pharmacy, AI, camera analytics, BLE/UWB/RFID, home care, and other smart-hospital capabilities.

These instructions are permanent development rules and apply to every Copilot Agent task in this repository.

---

# 2. Existing Technology Stack

Preserve the existing architecture unless an explicit approved requirement requires a change.

Primary stack:

* Backend: FastAPI / Python
* Database: PostgreSQL
* ORM: SQLAlchemy
* Database migrations: Alembic
* Frontend: React / TypeScript
* Authentication: JWT
* Cache / ephemeral coordination: Redis
* Real-time communication: WebSocket / Redis Pub/Sub
* Deployment: Docker / Docker Compose
* Architecture: Multi-tenant HMS

Do not introduce a replacement framework, database, ORM, frontend framework, or messaging technology without explicit approval.

---

# 3. Development Philosophy

This is an existing application.

Do not rebuild modules simply because another implementation appears cleaner.

For every task:

1. Inspect existing implementation first.
2. Determine what already works.
3. Determine what is partially implemented.
4. Determine what is actually missing.
5. Modify only what is necessary.
6. Preserve backward compatibility where reasonable.
7. Avoid unrelated refactoring.
8. Add regression tests.
9. Run existing tests.
10. Report exactly what changed.

Never assume an issue described in a planning document still exists.

Verify the current source code before changing it.

---

# 4. Phase Execution Rule

The HMS stabilization roadmap is defined in:

`docs/HMS_STABILIZATION_PLAN.md`

Copilot may read the entire roadmap for architectural context.

However:

**Implement only the phase explicitly requested by the user.**

Never automatically continue to another phase.

At the end of every phase:

* stop
* report results
* wait for review/approval

If the current phase has:

* failing tests
* unresolved P0 issue
* migration failure
* security regression
* unresolved architectural conflict

do not mark it complete.

---

# 5. Multi-Tenant Architecture

Tenant isolation is a critical security boundary.

Every hospital's operational and clinical data must remain isolated.

For authenticated tenant users:

`tenant_schema from JWT = authoritative tenant`

A client-controlled header, query parameter, request body field, cookie, or frontend value must never allow a user to switch to another tenant.

Do not trust:

`X-Tenant-Schema`

for normal tenant authorization.

Super Admin must use dedicated platform APIs.

Super Admin must not automatically receive unrestricted clinical access to all hospitals.

All tenant-sensitive database operations must execute within verified tenant context.

Never introduce cross-tenant queries without explicit platform-level authorization.

---

# 6. PostgreSQL Is the System of Record

PostgreSQL is authoritative for persistent HMS data.

Redis must never become the only store for:

* patient information
* visits
* appointments
* clinical records
* prescriptions
* lab records
* pharmacy transactions
* billing
* audit records

Redis may be used for:

* caching
* Pub/Sub
* WebSocket coordination
* refresh-token blocklists
* temporary distributed state
* rate limiting
* short-lived locks where appropriate

Loss or restart of Redis must not cause loss of committed hospital transactional data.

---

# 7. Encounter Architecture

`visit_id` is the primary operational encounter identifier for OPD.

The expected relationship is:

Patient
→ Appointment (optional)
→ Visit

Visit connects the encounter to:

* QueueToken
* Vitals
* Consultation
* Prescription
* LabOrder
* Invoice/Billing
* Feedback
* other encounter-specific records

Do not identify an encounter only using:

`patient_id + date`

A patient may have multiple encounters on the same day.

Legacy fallback logic may temporarily remain where required for backward compatibility, but new functionality must use `visit_id`.

---

# 8. Canonical OPD Visit State Machine

The OPD clinical lifecycle is:

REGISTERED

→ WAITING_FOR_NURSE

→ IN_PRE_VITAL

→ WAITING_FOR_DOCTOR

→ IN_CONSULTATION

→ CONSULTATION_COMPLETED

→ CLOSED

Also support:

CANCELLED

where permitted.

`VisitWorkflowService` is the authoritative location for OPD visit state transitions.

Do not directly assign `visit.status` from:

* API routes
* Pharmacy
* Lab
* Billing
* frontend requests
* unrelated services

All transitions must pass through the central workflow service.

Invalid transitions must be rejected.

---

# 9. Separate Domain Workflows

Do not overload `Visit.status`.

Pharmacy, Lab, Billing and future operational modules maintain independent lifecycle states.

Examples:

## Pharmacy

* PENDING
* CALLED
* DISPENSING
* PARTIALLY_DISPENSED
* DISPENSED
* CANCELLED
* OUT_OF_STOCK

## Lab

* ORDERED
* SAMPLE_PENDING
* SAMPLE_COLLECTED
* PROCESSING
* RESULT_READY
* VERIFIED
* COMPLETED
* CANCELLED

## Billing

* DRAFT
* PENDING
* PARTIALLY_PAID
* PAID
* CANCELLED
* REFUNDED

Do not create Visit states such as:

* dispatched_pharmacy
* dispatched_lab
* dispatched_both
* billing_pending

Downstream workflows must reference the Visit rather than replace its clinical state.

---

# 10. Reception Workflow

Both reception paths must converge into the same OPD lifecycle.

## Walk-In

Search Patient
→ Existing Patient OR Register Patient
→ Select Department
→ Select Doctor
→ Create Visit
→ Create Queue Token
→ WAITING_FOR_NURSE

## Appointment

Find Appointment
→ Check-In
→ Create Visit linked to Appointment
→ Create Queue Token
→ WAITING_FOR_NURSE

Appointment check-in must not place the patient directly into the Doctor Queue.

---

# 11. Nurse Workflow

Nurse workflow is:

WAITING_FOR_NURSE
→ Call Patient
→ Start Pre-Vitals
→ IN_PRE_VITAL
→ Save Draft if required
→ Complete Pre-Vitals
→ WAITING_FOR_DOCTOR

Pre-vitals should support at minimum:

* temperature
* pulse
* respiratory rate
* BP systolic
* BP diastolic
* SpO2
* pain score
* height
* weight
* BMI
* blood glucose
* chief complaint
* allergies
* Known No Allergies
* general condition
* level of consciousness
* nurse notes

BMI must be automatically calculated from height and weight.

Completing pre-vitals should publish the appropriate real-time queue event.

---

# 12. Doctor Workflow

Doctor workflow is:

WAITING_FOR_DOCTOR
→ Call Patient
→ Open Consultation
→ IN_CONSULTATION
→ Save Draft
→ Complete Consultation
→ CONSULTATION_COMPLETED

Doctors must only see authorized patients.

Backend filtering is mandatory.

Frontend filtering alone is insufficient.

Normal OPD consultation must not start before required pre-vitals are completed unless an explicitly authorized bypass workflow exists.

Any bypass must be audited.

---

# 13. Clinical Documentation

Consultations should support:

* chief complaint
* history of present illness
* past medical history
* examination
* provisional diagnosis
* final diagnosis
* ICD-10
* advice
* notes
* follow-up
* Draft
* Completed
* controlled Amendment

Completed clinical records must not be silently overwritten.

Amendments must preserve auditability.

---

# 14. Prescription Architecture

Prefer structured prescriptions.

Prescription header should reference:

* visit
* consultation
* doctor
* status

Prescription items should support:

* medicine
* medicine-name snapshot
* strength
* dose
* route
* frequency
* duration
* quantity
* instructions

Avoid using an uncontrolled JSON medicine list as the long-term pharmacy contract.

---

# 15. Authentication and Password Security

Staff accounts created with temporary/default passwords must support:

`must_change_password`

New/reset staff passwords must force password change before normal application access.

Password change must update:

* must_change_password
* password_changed_at

Refresh-token revocation must remain functional.

Never log:

* passwords
* JWTs
* refresh tokens
* API secrets
* payment secrets

---

# 16. Authorization

Backend authorization is mandatory.

Frontend route/menu hiding is only UX.

Role access must be enforced server-side.

Typical roles include:

* receptionist
* nurse
* doctor
* pharmacist
* billing
* lab
* hospital_admin
* super_admin

Use least privilege.

A role must not receive access merely because a frontend route is available.

---

# 17. Tenant Feature Controls

Tenant features must be enforced at:

1. backend API
2. frontend route
3. frontend navigation

Backend enforcement is authoritative.

Redis may cache feature state.

PostgreSQL remains authoritative.

---

# 18. Auditability

Important HMS actions must be auditable.

Audit where appropriate:

* login/logout
* password reset
* patient create/update
* visit creation
* visit state transitions
* vitals
* consultation completion/amendment
* prescriptions
* lab
* pharmacy dispensing
* invoice changes
* discounts
* refunds
* user/role changes
* tenant changes
* feature changes

Audit records should include where appropriate:

* tenant
* user
* role
* action
* entity type
* entity id
* visit_id
* previous value
* new value
* timestamp
* request metadata

Never audit secrets.

---

# 19. Database Changes

All database schema changes must use Alembic.

Never manually modify database structures as the implementation mechanism.

Every migration must:

* have a clear purpose
* support upgrade
* support downgrade where practical
* preserve existing data
* avoid destructive changes without explicit approval

Do not create migrations when the existing schema already supports the requirement.

---

# 20. API Design

Prefer domain-oriented APIs.

Validate all external inputs.

Never trust frontend validation alone.

Use appropriate HTTP status codes.

Avoid exposing internal exception details.

Prevent mass assignment of protected fields such as:

* tenant
* status
* role
* payment state
* audit identity

Workflow states must be changed through controlled domain operations.

---

# 21. Payment/Webhook Security

External payment webhooks must:

1. read raw request
2. verify provider signature
3. reject invalid signatures
4. parse trusted payload
5. resolve tenant context from verified provider contract
6. validate tenant
7. open tenant-scoped database session
8. perform idempotent business processing

Never default a webhook to an arbitrary tenant.

For Razorpay, tenant resolution must follow the currently validated contract:

1. order entity notes
2. payment notes fallback
3. reject if tenant cannot be safely resolved

Conflicting tenant values should be treated as suspicious.

---

# 22. Real-Time Events

WebSocket/Redis events may support:

* queue changes
* nurse call
* vitals start/completion
* doctor call
* consultation start/completion
* Pharmacy
* Lab
* Billing

Events must be tenant isolated.

Do not treat WebSocket delivery as the system of record.

Clients must be able to refresh authoritative state from APIs.

---

# 23. Operational Timing

Preserve timestamps required for future TAT/SLA analytics.

Important timestamps include:

* arrival
* registration completion
* nurse queue entry
* nurse called
* pre-vitals start
* pre-vitals completion
* doctor queue entry
* doctor called
* consultation start
* consultation completion
* pharmacy queue/dispensing
* lab order/sample/result
* billing start/completion

Do not prematurely implement AI prediction before reliable event/timestamp capture exists.

---

# 24. Testing Rules

Every phase and significant bug fix requires automated regression tests.

Backend tests belong under:

`backend/tests/`

Tests should cover:

* success paths
* invalid input
* unauthorized roles
* tenant isolation
* state-transition errors
* repeat/same-day encounters
* backward compatibility where applicable

Bug fixes should include a regression test reproducing the original bug whenever practical.

Do not claim a phase is verified merely because Python compiles.

Run relevant pytest suites.

When frontend dependencies are installed, run:

* TypeScript validation
* frontend build
* relevant frontend tests

If dependencies are unavailable, state that clearly.

---

# 25. Code Quality

Prefer:

* small focused functions
* explicit service boundaries
* reusable validation
* typed schemas
* enums/constants
* meaningful naming
* transaction safety
* clear error handling

Avoid:

* duplicate business logic
* magic strings
* direct workflow-state writes
* broad exception swallowing
* unrelated refactoring
* dead compatibility code without explanation
* unnecessary new dependencies

---

# 26. Backward Compatibility

When correcting legacy behavior:

1. identify whether existing records depend on it
2. introduce a safe compatibility path if necessary
3. add regression coverage
4. document the compatibility behavior
5. plan its eventual removal

Example:

Legacy QueueToken records without `visit_id` may temporarily use patient/date fallback.

New QueueTokens must use `visit_id`.

---

# 27. Scope Control

Do not implement these merely because they appear in future architecture discussions:

* IP
* ER
* OT
* ICU
* camera analytics
* facial recognition
* BLE/UWB
* RFID
* AI triage
* AI prescription
* agentic billing
* predictive queueing
* advanced fraud detection
* home care

Only implement them when explicitly assigned.

Design current foundations so future modules can integrate cleanly.

---

# 28. Required End-of-Task Report

After every implementation task report:

## Requirements Checked

What was already implemented?

What was missing?

## Changes

* files changed
* APIs changed
* models changed
* migrations added
* frontend changes

## Tests

* tests added
* commands executed
* exact results

## Regressions

Any regression found while implementing the phase.

## Outstanding Issues

Anything not completed.

## Risks

Potential compatibility/security/data risks.

## Phase Status

Use one:

* COMPLETE
* COMPLETE WITH FOLLOW-UP
* BLOCKED
* INCOMPLETE

Never start the next phase automatically.
