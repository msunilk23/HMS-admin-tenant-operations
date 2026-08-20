# HMS OPD Post-Stabilization Review & Copilot Agent Plan

## Purpose
This is the implementation backlog after completion of the original 24-phase OPD stabilization program. Use it with `.github/copilot-instructions.md`, `docs/HMS_STABILIZATION_PLAN.md`, `docs/OPD_WORKFLOW.md`, `docs/ARCHITECTURE.md`, and `docs/DATA_MODEL.md`.

**Rule:** inspect current code first; implement only verified gaps; execute one phase at a time; add tests; stop for review before the next phase.

## Agent execution rules
1. Read the permanent instructions and HMS docs first.
2. Verify each finding against current code; do not blindly rewrite.
3. Preserve tenant isolation, `visit_id` encounter linkage, and `VisitWorkflowService` as the Visit-state authority.
4. Pharmacy, Lab, and Billing retain independent states.
5. Use Alembic for schema changes.
6. Avoid unrelated refactoring and unnecessary dependencies.
7. Add regression tests and run relevant existing suites.
8. Never silently swallow mandatory workflow/security failures.
9. At phase end report: requirements checked, gaps, files/models/migrations/APIs/frontend changed, tests + exact results, regressions, unresolved issues, risks, and phase status.
10. Do not start the next phase automatically.

# RELEASE A — OPD CORE v1 UAT READINESS

## Phase A1 — Workflow Transaction Integrity (P0)
Inspect consultation, vitals, queue, closure and cancellation code for patterns such as `except ValueError: pass` around `VisitWorkflowService.transition`. Mandatory transition failures must stop the operation, roll back the transaction, return a controlled conflict/error, and prevent domain/Visit state divergence. Add tests proving invalid transitions commit neither side.

## Phase A2 — Super Admin Clinical Access Review (P0/P1)
Search clinical APIs for `super_admin`. Platform Super Admin should manage tenants, subscriptions/features, platform configuration/health and authorized platform audit, but should not automatically modify patient demographics, vitals, consultations, prescriptions, dispensing, lab results, or clinical records. If support access is genuinely required, implement explicit tenant selection, authorization, reason, audit and preferably time-bounded access. Test denial of unauthorized clinical mutations and continued tenant isolation.

## Phase A3 — Clean Environment Release Gate (P0)
From a fresh environment: install backend dependencies, initialize DB, run Alembic upgrade, run complete pytest suite; then `npm ci`, `npx tsc --noEmit`, `npm run build`, and frontend tests if configured. Validate Docker images/Compose, PostgreSQL, Redis, health endpoints, login, tenant login, Super Admin login and core OPD smoke flow. Record exact commands/results. Missing dependencies such as `python-jose` must be fixed in declared requirements.

## Phase A4 — Doctor Schedule & Availability Engine
Replace generic hard-coded 09:00–17:00/15-minute availability with real doctor schedules. Reuse existing models if present; otherwise add equivalents of `DoctorSchedule` (doctor, department, branch/location, weekday, start/end, slot duration, capacity, effective dates, room, appointment type, active) and `DoctorScheduleException` (leave, holiday, blocked period, emergency block, custom hours). Authoritative availability = schedule - bookings - leave - blocks - holidays - capacity used. Expose one API used by Reception and later Patient App/Kiosk. Make final-slot booking concurrency-safe. Test normal schedules, leave, partial blocks, holidays, capacity, effective dates, concurrent booking, and tenant isolation.

## Phase A5 — Appointment Capacity
Support configurable capacity, not only one patient per 15-minute slot. Examples: 10:00–10:15 capacity 3; or 10:00–11:00 capacity 12. Cancelled bookings release capacity. Prevent overbooking unless an explicit audited override policy exists. Add race-condition tests for the last capacity.

## Phase A6 — Basic Clinical Alert / Allergy Banner
Inspect current allergy handling. Add a patient clinical alert foundation if missing, e.g. patient, alert type, severity, description, active/resolved state, creator/resolver and timestamps. Surface active critical alerts prominently to authorized Nurse/Doctor/Pharmacy screens. This is a warning layer, not an AI diagnosis engine.

## Phase A7 — Queue SLA & Priority Foundation
Use reliable OPD timestamps to provide configurable SLA thresholds for `WAITING_FOR_NURSE` and `WAITING_FOR_DOCTOR`, operational counts, longest waits and breaches. Support approved priority categories (e.g. NORMAL, SENIOR_CITIZEN, PREGNANT, DISABLED, URGENT, EMERGENCY) with reason, assigned_by and assigned_at. Keep policy configurable and auditable.

## Release A acceptance
Ready for hospital UAT only when: A1/A2 are resolved, clean backend regression and frontend build pass, Docker/deployment smoke test passes, real doctor scheduling/capacity exists, basic clinical alerts and queue SLA/priority are operational, and no P0 remains.

# RELEASE B — OPD v1.1 CLINICAL & OPERATIONAL ENHANCEMENTS
Validate these against UAT before broad implementation.

## Phase B1 — Appointment Waitlist
Add WAITLISTED → OFFERED → ACCEPTED → BOOKED with EXPIRED/CANCELLED. On cancellation, safely offer capacity to an eligible candidate for a configurable acceptance window. Must be concurrency-safe.

## Phase B2 — Appointment Reminders
Configurable reminders (previous day / hours before) over SMS, WhatsApp, email and later push. Track scheduled/sent/status/failure. Notification failure must not roll back the appointment.

## Phase B3 — No-Show Automation
After appointment time + configurable grace period, if no arrival/check-in exists, mark NO_SHOW with audit. Allow authorized correction.

## Phase B4 — Longitudinal Patient Allergy Model
Move allergies toward patient-level longitudinal history: allergen, reaction, severity, status, recorded/verified by/at, and clinically approved NKDA handling. Encounter workflow should review/confirm/update without destructive overwrite.

## Phase B5 — Longitudinal Clinical History
Consider structured active problems, past history, current medications, surgical history and relevant social history, while avoiding premature over-structuring. Preserve historical changes.

## Phase B6 — Previous Visit Timeline
Doctor patient context should show chronological prior visits with department, doctor, diagnosis, prescriptions, labs, follow-up and documents, with drill-down and efficient pagination/lazy loading.

## Phase B7 — Referral Workflow
Add formal referral: patient, from_visit/from_doctor, to_department/to_doctor, reason, priority and states REFERRED/BOOKED/SEEN/COMPLETED/CANCELLED. Integrate with appointment booking.

## Phase B8 — Actionable Follow-Up
Convert follow-up advice into a recommendation that can generate/book a future appointment and reminders, linked to the originating Visit/Consultation.

## Phase B9 — Patient Consent Framework
Versioned consent records: patient, optional visit, consent type/version, accepted/rejected, timestamp, channel, captured_by, reference and revocation where applicable. Prepare for treatment, privacy/data, teleconsultation, home service and procedure consent subject to policy.

## Phase B10 — Patient Document Management
Secure metadata for outside prescriptions, lab reports, referrals, insurance documents, discharge summaries and imaging-related files. Use private object/file storage with controlled access; do not put large binaries in PostgreSQL without explicit justification.

## Phase B11 — Configurable Critical Vitals Alerts
Clinically governed configurable thresholds, severity, display/acknowledgement/audit. No autonomous diagnosis and no replacement of clinical judgement.

## Phase B12 — Doctor Room / Consultation Location
Model doctor + schedule + department + branch + room + effective time + temporary room changes. Expose appropriate location to Reception, Nurse, token display, future Kiosk/App.

# RELEASE C — PATIENT DIGITAL PLATFORM
Use the same HMS backend/domain source of truth; do not create incompatible mobile/kiosk databases or business rules.

## Phase C1 — Patient Identity & Family Profiles
Patient-facing authentication, mobile verification, secure UHID linking/new onboarding, and family/dependent profiles. Each person remains a distinct Patient/UHID. Prevent unauthorized record linking.

## Phase C2 — Patient OPD Appointment Booking
Hospital/branch → speciality → doctor → date → real available slots → patient/family member → confirm → payment if required → appointment → QR/booking code. Consume the same Availability Engine as Reception.

## Phase C3 — Arrival / Check-In Service
Create one authoritative service for Reception, Kiosk, Patient App and entrance QR; future BLE/RFID/camera can plug in. Suggested `PatientArrival`: patient, optional appointment/visit, branch/location, channel, arrived_at, checked_in_at, status, device/kiosk. Initial channels: RECEPTION, KIOSK, PATIENT_APP, ENTRANCE_QR. Keep arrival/check-in separate from canonical `Visit.status`. Successful check-in creates/confirms Visit + QueueToken → `WAITING_FOR_NURSE`. Must be idempotent.

## Phase C4 — Kiosk Application / Separate URL
Dedicated restricted `/kiosk` or branch-specific UI/device identity; never expose staff UI. Existing appointment flow: scan QR/securely identify → validate → confirm arrival → check-in → Visit → QueueToken → `WAITING_FOR_NURSE` → show token/location. Approved identity options may include QR, booking code, mobile+OTP, or UHID plus additional verification.

## Phase C5 — Kiosk Walk-In / Slot Booking
No appointment → identify/register patient → speciality → doctor/any doctor → authoritative available slots → book → arrive → Visit → QueueToken → `WAITING_FOR_NURSE`. No separate kiosk availability logic.

## Phase C6 — Appointment Arrival Window
Hospital-configurable early/late self-check-in windows and late-arrival policy. Do not hard-code example timings.

## Phase C7 — Entrance QR / Mobile Self Check-In
Patient App scans branch/entrance QR → verify branch → resolve today's appointment → check-in → Visit/Queue. Do not rely solely on GPS indoors. BLE/Wi-Fi/UWB/camera presence are future extensions.

## Phase C8 — Live Queue / Token Status
Patient-specific token, department, doctor, room, status, number ahead where permitted, and waiting estimate only when reliable. WebSocket for UX; APIs/PostgreSQL authoritative; never expose other patients' identities.

## Phase C9 — Patient Payments
Secure eligible invoices/payment initiation/status/receipt/retry. Never trust frontend redirect as payment success. Preserve raw-body signature verification, safe tenant resolution, idempotency, tenant-scoped transaction and audit.

## Phase C10 — Patient Lab Booking
Test/package → hospital or home collection → date/slot → price/payment → LabOrder → sample → processing → verified result → report. Same Lab domain must support doctor-ordered, self-booked, walk-in and home collection.

## Phase C11 — Home Sample Collection
Collection address/slot, assigned phlebotomist, travel/arrival, sample collected, specimen tracking/handover and Lab processing. Preserve chain of custody/audit.

## Phase C12 — Home Services
Nurse visit, injection, dressing, physiotherapy, doctor home visit, sample collection: service → address → slot → price/payment → booking → staff assignment → arrival → service start → clinical/service notes → completion → feedback. Do not force Home Services into OPD Visit; introduce an appropriate ServiceBooking/HomeServiceEncounter domain after inspecting current models.

## Phase C13 — Notifications
Shared architecture for appointment confirmation/reminder/cancellation/waitlist/check-in/queue/payment/lab result/home service/feedback over SMS, WhatsApp, email and push. Track delivery status; provider outage must not block core HMS transactions.

## Phase C14 — Patient Feedback
Reuse visit-linked Feedback through app, QR, kiosk and SMS/WhatsApp link. Prepare configurable low-rating escalation; do not expose internal staff notes.

# Patient Digital Platform architecture

```text
                    HMS API PLATFORM
                           │
          ┌────────────────┼────────────────┐
          │                │                │
      Staff Web       Patient App       Kiosk/PWA
          │                │                │
          └────────────────┴────────────────┘
                           │
                    Domain Services
                           │
                      PostgreSQL
                           │
                 Redis / Real-Time Layer
```

Shared services: patient identity/linking, doctor availability, appointment, arrival/check-in, Visit creation, Queue, Billing/Payment, Lab and Notifications.

# Future Smart Hospital preparation
Do not implement BLE/UWB/RFID/camera presence, facial recognition, pharmacy fraud camera AI, AI triage, predictive queue AI or agentic billing under this plan unless separately approved. Preserve extension points such as `arrival_channel`, reliable event timestamps and human-authorized clinical workflows.

# Hospital UAT plan
After Release A, test with real role users.

- Reception: search, registration, duplicate handling, walk-in, appointment, check-in, cancellation, queue.
- Nurse: queue, call, start/draft/complete vitals, alerts.
- Doctor: queue, patient context, consultation, diagnosis, prescription, lab order, completion.
- Pharmacy: prescription reception, dispensing, partial/out-of-stock/cancellation.
- Lab: order, sample, processing, result, verification.
- Billing: invoice, payment, discount, refund, online payment.
- Hospital Admin: staff, roles, features, roster, doctor schedule, operational dashboard.

Classify UAT findings as: DEFECT, UX IMPROVEMENT, CONFIGURATION, TRAINING ISSUE, or NEW REQUIREMENT. Do not treat every request as a defect.

# Final release gates
Before tagging OPD Core v1: no P0; accepted P1 resolved/deferred; full backend regression; frontend build; clean and representative-existing-DB migrations; Docker deployment; tenant isolation; RBAC; workflow transition; appointment concurrency; payment webhook tests; UAT sign-off; backup/restore validation; release notes.

# Copilot Agent prompt template

```text
Read:
- .github/copilot-instructions.md
- docs/HMS_STABILIZATION_PLAN.md
- docs/OPD_WORKFLOW.md
- docs/ARCHITECTURE.md
- docs/DATA_MODEL.md
- docs/HMS_OPD_POST_STABILIZATION_AGENT_PLAN.md

The original 24-phase OPD stabilization program is complete.

Execute ONLY Phase <PHASE_ID> — <PHASE_NAME> from docs/HMS_OPD_POST_STABILIZATION_AGENT_PLAN.md.

Before changing code:
1. Inspect current implementation.
2. Verify each finding still exists.
3. Report already implemented / partial / missing / incorrect.
4. Preserve completed OPD stabilization work.
5. Do not make unrelated refactors.

Then implement only verified gaps.

Preserve multi-tenant isolation, visit_id encounter linkage, VisitWorkflowService authority, and independent Pharmacy/Lab/Billing states. Use Alembic for schema changes. Add regression tests and run relevant existing tests. Run frontend checks when frontend changes are made.

At completion report requirements checked, files changed, migrations, APIs, frontend, tests + exact results, regressions, unresolved issues, risks and phase status.

Do NOT start the next phase. Stop and wait for review.
```

# Recommended execution order

```text
A1 Workflow Transaction Integrity
→ A2 Super Admin Clinical Access
→ A3 Clean Environment Release Gate
→ A4 Doctor Schedule & Availability
→ A5 Appointment Capacity
→ A6 Clinical Alert Foundation
→ A7 Queue SLA/Priority
→ OPD UAT
→ UAT Fixes
→ OPD Core v1
```

Then select Release B items based on UAT. After OPD Core sign-off:

```text
Patient Identity
→ Appointment Booking
→ Arrival Service
→ Kiosk
→ Walk-In Self Booking
→ QR Check-In
→ Live Queue
→ Payments
→ Lab Booking
→ Home Collection
→ Home Services
→ Notifications
→ Patient Digital Platform UAT
```

Only after OPD and Patient Digital Platform are stable: `IP / ER / OT / ICU`.

# Architecture rule to preserve

**ONE HMS DOMAIN PLATFORM** serving Staff Web, Patient App, Kiosk and future clients. Maintain one Patient identity model, Doctor scheduling engine, Appointment domain, Arrival/Check-In service, Visit/Encounter foundation, Queue, Lab, Billing/Payment and tenant/security architecture.
