# Release A Final Readiness and Hospital OPD UAT

## Purpose

This is the controlling execution record for the Release A gate after Pharmacy
P25-P34 was merged into `phase1-stabilization`. It supplements
`HMS_OPD_POST_STABILIZATION_AGENT_PLAN.md`; it does not authorize Release B,
Lab expansion, Kiosk, IP, ER, OT, ICU, deployment, or production changes.

## Baseline

| Item | Expected |
| --- | --- |
| Branch | `phase1-stabilization` |
| Merge commit | `4c226db4840a76a4ce976180b72ea473beb29c54` |
| Alembic heads | One |
| P34 accepted head (historical, do not change) | `0088` |
| Current Release A candidate head | `0089` |
| Backend accepted baseline | `371 passed` with PostgreSQL available |
| Frontend unit baseline | `35 passed` |
| P34 PostgreSQL baseline | `4 passed` |
| P34/general-dashboard Chromium baseline | `6 passed` |

## Migration policy for `0089`

`0089_decouple_super_admin_from_tenants.py` is an **intentionally forward-only
policy migration**, not a defect. Its `upgrade()` unconditionally sets
`tenant_id = NULL` and `tenant_name = NULL` for every `role = 'super_admin'`
user, and its `downgrade()` deliberately raises `RuntimeError` whenever any
user row is tenant-independent — which is guaranteed immediately after
upgrade. This is approved, permanent behaviour: Super Admin must remain
platform-level and tenant-independent going forward.

- `0088` remains the last automatically reversible Pharmacy (P25–P34)
  migration; CI's downgrade/re-upgrade smoke exercise is scoped to
  `0088 -> 0087 -> 0088` and then advances forward to `0089` — it does not
  attempt an automated downgrade from `0089`.
- Do not modify migration `0089` — it has already been applied to a
  persistent database (`shankar_hospitals`/`public` in the reviewed
  environment) and per policy an already-applied migration is not edited.

### Controlled manual rollback runbook (disaster recovery only)

Automated tooling must never attempt this. If an operator must genuinely
revert past `0089` in a disaster-recovery scenario:

1. Confirm the business decision to restore Super Admin users to a specific
   tenant is intentional and approved — this is a real data/policy change,
   not a mechanical reversal.
2. For each affected `role = 'super_admin'` row, manually decide and set an
   explicit `tenant_id`/`tenant_name` (there is no automatic or fabricated
   default — assigning a tenant to a platform-level user is a business
   decision that must be made explicitly, per user, by an authorized owner).
3. Only after every `public.users` row has a non-null `tenant_id` and
   `tenant_name` will `alembic downgrade 0088` succeed (its guard clause
   checks exactly this).
4. Prefer restoring from a pre-`0089` backup over a live downgrade whenever
   possible; a live downgrade changes the meaning of existing Super Admin
   accounts and should be a last resort.

## Automated release gates

- [ ] Fresh dependencies install from declared manifests.
- [ ] GitHub Actions secrets `CI_POSTGRES_PASSWORD` and `CI_SECRET_KEY` are configured with CI-only values.
- [ ] Clean database upgrades to sole head `0089`.
- [ ] Representative existing database upgrades to `0089`.
- [ ] Reversible boundary `0088 -> 0087 -> 0088` completes, then forward upgrade to `0089` succeeds (no automated downgrade past `0089`).
- [ ] Every configured schema reports `0089`.
- [ ] Complete backend suite passes with zero unexpected skips.
- [ ] TypeScript, ESLint, unit tests, and production build pass.
- [ ] Docker Compose configuration validates.
- [ ] Backend and frontend container images build.
- [ ] PostgreSQL and Redis become healthy.
- [ ] Backend `/health`, OpenAPI, frontend login, and Nginx endpoints respond.
- [ ] Tenant and Super Admin authentication smoke passes.
- [ ] Tenant isolation, RBAC, workflow transaction, appointment concurrency,
      and Razorpay webhook security suites pass.
- [ ] Disposable PostgreSQL backup/restore exercise passes.

## Current execution evidence

Execution date: 2026-08-31 UTC.

| Gate | Result | Evidence/limitation |
| --- | --- | --- |
| Target synchronization | PASS | Local review branch equals `origin/phase1-stabilization` at `4334f22`, ahead `0`, behind `0` |
| Repository migration graph | PASS | Static analysis and `alembic heads` return only `0089 (head)` |
| Fresh backend dependency install | PASS | New Python 3.12 virtual environment installed only `backend/requirements.txt` |
| Fresh frontend dependency install | PASS | `npm ci` installed the lockfile successfully |
| Backend compile | PASS | `python -m compileall -q app` |
| Backend suite without PostgreSQL | PARTIAL | `279 passed, 92 skipped`; database-dependent skips are not accepted as release evidence |
| TypeScript | PASS | `npm run type-check` |
| ESLint | PASS | `npm run lint` |
| Frontend unit tests | PASS | `35 passed` |
| Frontend production build | PASS WITH ADVISORY | Build completed; existing bundle-size warning remains |
| Docker/Compose build and health | BLOCKED | Docker is not installed in the review runner |
| PostgreSQL/Redis startup and migrations | BLOCKED | No Docker or external service endpoints are available in the review runner |
| Browser role workflows | BLOCKED | Requires the PostgreSQL-backed application stack |
| Backup/restore execution | BLOCKED | Requires PostgreSQL client/server access; automated gate added to CI |
| Business role UAT | PENDING | Must be performed by named Hospital UAT users |

## Hospital role UAT

Use named UAT users. Record evidence without passwords, tokens, payment secrets,
or patient-identifying screenshots.

### Reception

- [ ] Search existing patient by permitted identifiers.
- [ ] Register patient and verify duplicate handling/override authorization.
- [ ] Register walk-in and confirm `WAITING_FOR_NURSE`.
- [ ] Book and check in an appointment.
- [ ] Confirm schedule, leave/block, capacity, cancellation, and last-slot rules.
- [ ] Cancel an eligible visit and verify audit/queue removal.

### Nurse

- [ ] See only the permitted queue/department.
- [ ] Call patient and start pre-vitals.
- [ ] Save and reopen a draft.
- [ ] Complete pre-vitals and hand off to Doctor queue.
- [ ] Verify allergy/critical alert banner and queue SLA/priority display.

### Doctor

- [ ] See only the authorized Doctor queue.
- [ ] Open consultation only after required pre-vitals.
- [ ] Save/reopen consultation draft.
- [ ] Record controlled ICD-10 and justified free-text diagnosis.
- [ ] Prescribe in-stock and zero-stock formulary medicines.
- [ ] Create Lab order and complete consultation.

### Pharmacy

- [ ] Receive prescription independently of Visit status.
- [ ] Validate full, partial, outside-purchase, substitution, and out-of-stock paths.
- [ ] Complete billing-authorized dispensing and verify batch/ledger deduction.
- [ ] Exercise approved return/quarantine/transfer/count permissions.
- [ ] Verify Pharmacy dashboard isolation and financial redaction.

### Lab

- [ ] Receive the Doctor order with patient, visit, consultation, facility, and test snapshots.
- [ ] Progress sample collection, processing, result entry, verification, and completion.
- [ ] Verify unauthorized result entry/verification is denied.
- [ ] Verify Doctor result visibility and Lab invoice linkage/idempotency.

### Billing

- [ ] Create/review registration, consultation, Lab, and Pharmacy charges.
- [ ] Process cash and configured online-payment test paths.
- [ ] Verify retry/idempotency and signed webhook handling.
- [ ] Exercise permitted discount, cancellation, refund, receipt, and document versioning.

### Hospital Admin

- [ ] Manage staff without granting unauthorized permissions.
- [ ] Manage Doctor schedules, exceptions, locations, and capacity.
- [ ] Review roster, operational dashboard, alerts, reports, and audit.
- [ ] Verify feature changes affect API, navigation, and routes.

### Super Admin

- [ ] Authenticate through platform routes without tenant clinical context.
- [ ] Manage tenant status/features and approved Hospital Admin password reset.
- [ ] Confirm all tenant clinical read/mutation routes remain denied.

## Security and isolation matrix

- [ ] Tenant A cannot read or mutate Tenant B patient, visit, clinical, Pharmacy,
      Lab, Billing, audit, or dashboard data.
- [ ] Client-supplied tenant/facility headers cannot override JWT/server scope.
- [ ] Receptionist, Nurse, Doctor, Pharmacist, Lab Technician, Billing Officer,
      Hospital Admin, and Super Admin negative-role cases return controlled denial.
- [ ] Invalid workflow transitions roll back both domain and Visit changes.
- [ ] Replayed idempotency keys cannot duplicate financial, stock, or clinical operations.
- [ ] Logs and evidence contain no credentials, tokens, payment secrets, or PHI.

## Finding register

Use one classification: `DEFECT`, `UX IMPROVEMENT`, `CONFIGURATION`,
`TRAINING ISSUE`, or `NEW REQUIREMENT`.

| ID | Classification | Severity | Role/module | Scenario | Expected | Actual | Evidence | Owner | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RA-001 | CONFIGURATION | High | Release environment | Execute Docker/DB gates | Docker and PostgreSQL available | Pending execution in an authorized release runner | This record | DevOps | OPEN |
| RA-002 | NEW REQUIREMENT | High | Business UAT | Obtain hospital sign-off | Named role users complete UAT | Business execution not yet recorded | Role checklist above | Business owner | OPEN |
| RA-003 | DEFECT | High | Payment security | Review committed documentation | No secret values in repository content/history | A webhook-secret value was committed in the payment guide; working-tree documentation is redacted | `PAYMENT_TESTING_GUIDE.md` | Security/DevOps | ROTATE BEFORE UAT |
| RA-004 | DEFECT | High | Docker Compose | Start from documented repository files | Compose resolves PostgreSQL and pgAdmin configuration without embedded credentials | Compose referenced an absent `infra/postgres.env`; corrected to require documented root `.env` variables with no credential fallbacks | `infra/docker-compose.yml` | Development | FIXED, CI RETEST PENDING |

## Release notes draft

Release A consolidates the stabilized OPD platform and the accepted Pharmacy
P25-P34 stream. The candidate includes multi-tenant security, canonical Visit
workflow transactions, Reception/Nurse/Doctor operations, controlled clinical
data, Doctor schedules and appointment capacity, clinical alerts, queue
SLA/priority, Pharmacy procurement/inventory/dispensing/billing/returns/stock
control/reporting, Lab master/order/result/billing linkage, Billing/payment,
audit, RBAC, feature enforcement, and operational documentation.

The database target is sole Alembic head `0089`. This candidate is for
controlled UAT only after the automated release workflow passes. It is not a
production deployment authorization.

## Sign-off decision

Current decision: **NOT YET RELEASE-READY**.

The code baseline may proceed to controlled Hospital UAT after every automated
gate passes in an environment with Docker, PostgreSQL, Redis, browser support,
and disposable backup/restore capacity. OPD Core v1 may be signed off only when
there is no unresolved P0, accepted P1 items are resolved or explicitly
deferred, and the Hospital UAT checklist has business-owner approval.

After Release A sign-off, the approved priority is:

1. Lab completion and UAT hardening.
2. Kiosk stream, after Patient Identity, authoritative Appointment Availability,
   and Arrival/Check-in contracts are confirmed.
