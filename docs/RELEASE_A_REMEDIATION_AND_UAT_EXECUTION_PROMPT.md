# Release A Remediation and Hospital OPD UAT — Authoritative Execution Prompt

## Purpose

Use this document as the complete execution contract for the remaining Release A work. Do not rely on prior chat history or invent missing requirements. The target branch is `phase1-stabilization`.

Release A may be declared **READY FOR CONTROLLED HOSPITAL UAT** only after every mandatory technical gate in this document passes. It may be declared **OPD CORE V1 SIGN-OFF READY** only after named Hospital users complete business UAT and all findings are resolved or formally accepted.

## Mandatory working rules

1. First inspect the active branch, HEAD, remotes, staged, unstaged and untracked files. Preserve every user change.
2. Do not commit, amend, merge, push, deploy, rebase, reset, stash, clean or delete files without explicit authorization.
3. Confirm the sole repository Alembic head and the head of every configured PostgreSQL schema before editing.
4. Review `RELEASE_A_FINAL_READINESS_AND_OPD_UAT.md`, `HMS_OPD_POST_STABILIZATION_AGENT_PLAN.md`, BRDs, TDDs, RBAC matrix, API/data-model documents, migration policy, and Pharmacy P30–P34 acceptance reports.
5. Treat backend authorization, tenant/facility isolation and database constraints as authoritative. UI hiding is not authorization.
6. Never add credentials, tokens, real passwords, patient data or insecure fallbacks to source, tests, logs or documentation.
7. Implement in the numbered order below. Stop and request a decision if an existing contract contradicts this document or a required business rule remains ambiguous.

## Accepted baseline

- Pharmacy P30–P34 is complete and accepted.
- The dedicated Pharmacy dashboard is `/pharmacy/dashboard`; its API is `/api/v1/pharmacy-dashboard`.
- Nurse Roster and controlled Lab Test Master work has been pushed to `phase1-stabilization`.
- The expected sole migration head before new work is `0089`; verify rather than assume.
- Existing OPD, Pharmacy P30–P34 and general HMS dashboard behavior must not regress.

## Release A task register

### RA-1 — Fresh-environment and infrastructure validation

Revalidate the complete branch from a clean, disposable environment:

- Validate `docker compose config`.
- Start PostgreSQL, Redis, backend and frontend and confirm health checks.
- Apply migrations from a fresh database to the sole head.
- Validate the documented reversible migration boundary and the intentional forward-only treatment of migration `0089`.
- Confirm tenant-user and Super Admin authentication without exposing credentials.
- Validate backup with `pg_dump` and restore with `pg_restore --exit-on-error` into a disposable database.
- Confirm the restored database head and tenant schema, then safely remove only the verified disposable database.

Do not modify an already-applied migration. Any new schema work must use the next valid revision after inspecting the repository graph.

### RA-2 — Nurse Roster completion and live verification

Required behavior:

- Hospital Admin can view daily/weekly rosters; create, edit and deactivate assignments; record attendance; create substitutions; search/filter; and review audit history.
- Deactivation and substitution require a non-empty reason.
- Assigned and substitute nurses must be active nurses in the same tenant/facility scope.
- Reject self-substitution, duplicates, overlapping assignments and invalid department/doctor references.
- Nurse has read-only access to the nurse's own roster, including substitute assignments.
- Nurse self-attendance is excluded.
- Super Admin has no tenant Nurse Roster access.
- Every mutation must produce an audit record with actor, timestamp, reason and correct before/after values.

Acceptance:

- Backend positive, negative, RBAC, isolation, duplicate, overlap and audit tests.
- Frontend component tests for loading, empty, error, validation, confirmation and successful mutation states.
- Live Chromium verification using a real `hospital_admin` account and a real Nurse account.
- If no working credential exists, reset it through the approved secure administrative flow; never add a known fallback password.

### RA-3 — Lab workflow security and transactional completion

Required role contract:

| Capability | Doctor | Nurse | Lab Technician | Receptionist | Hospital Admin | Super Admin |
|---|---:|---:|---:|---:|---:|---:|
| Order Lab test for authorized visit | Yes | No | No | No | Yes | No |
| View authorized detailed result | Yes | Limited clinical need only | Yes | No | Yes | No |
| Collect/process sample | No | No | Yes | No | Yes | No |
| Enter/edit result before verification | No | No | Yes | No | Yes | No |
| Verify/complete result | No | No | Yes | No | Yes | No |
| Download detailed Lab report | Authorized visit only | No | Yes | No | Yes | No |

Implementation requirements:

- Enforce the matrix on every list and direct-ID endpoint; do not rely only on list filtering.
- A Doctor may create/view/download only for a visit the Doctor owns or is explicitly authorized to access.
- Receptionist must not access detailed results or clinical reports.
- Nurse and Doctor must not enter results or advance Lab processing states.
- Validate state transitions server-side; reject skipped, reversed or role-invalid transitions.
- New orders must use an active controlled Lab Test Master entry. Reject free-text and duplicate test orders.
- Snapshot code, name, category, sample type, unit, reference range and price at order time.
- Keep `result_ready` and verification-pending items visible in the Lab Technician worklist.
- Trigger billing at verification. Invoice creation and verification must be one transaction: rollback verification on billing failure and return a controlled error.
- Make billing idempotent under retry and concurrency with a database constraint plus concurrent PostgreSQL tests.
- Distinguish missing price from an intentional zero price.
- Correct rejection/audit history so `old_value` is captured before changing status.
- Preserve tenant/facility isolation on list, create, update, result and report endpoints.

Acceptance:

- Full lifecycle, invalid-transition, direct-ID authorization, Doctor ownership, receptionist denial and cross-tenant/facility tests.
- Billing rollback, retry and real concurrency tests.
- Frontend component tests for Doctor Lab Results and Lab worklist states.
- Chromium Doctor order → Lab worklist → result entry → verification → Doctor result → Billing verification flow.

### RA-4 — Pharmacy OTC and external-prescription dispensing

This is mandatory Release A scope. It supplements OPD prescription dispensing; it does not replace or weaken it.

#### Sale classifications

Every Pharmacy sale must have an immutable classification:

- `OPD_PRESCRIPTION`
- `OTC`
- `EXTERNAL_PRESCRIPTION`

#### OTC rules

- Provide a dedicated Pharmacy screen, recommended route `/pharmacy/otc`.
- Allow walk-in customer sales without an OPD visit only for active medicines where `requires_prescription = false` and `is_controlled_drug = false`.
- Patient registration is optional for a permitted OTC sale; support an identifiable walk-in/customer reference according to existing billing rules.
- Reject prescription-only, controlled, inactive, quarantined, expired, recalled, blocked or insufficient-stock batches.

#### External-prescription rules

- Prescription-only or controlled medicines without an HMS OPD prescription require an `EXTERNAL_PRESCRIPTION` sale.
- Capture prescriber name, registration number, prescription date, issuing facility/clinic, prescription reference and attachment/document reference where supported.
- Require patient identity according to controlled-drug and billing policy.
- Require Pharmacist verification before dispensing.
- Controlled medicines must never use the simple OTC path.
- Apply quantity/refill/expiry restrictions from the approved medicine and regulatory contract. If these rules are not defined in repository specifications, stop for business approval instead of inventing them.
- require to upload the copy of the prescription - optional

#### Shared dispensing guarantees

- Use FEFO batch selection unless an authorized user explicitly selects an eligible batch with a recorded reason.
- Price, tax, discount and totals must be calculated server-side.
- Stock deduction, signed stock ledger entry, sale/dispense record and invoice/payment linkage must be transactional and idempotent.
- Prevent negative inventory and overselling with PostgreSQL locking/constraints and concurrency tests.
- Support only approved payment statuses and existing payment/webhook protections.
- Returns and refunds must integrate with accepted P30 behavior and retain the original sale classification.
- Enforce Pharmacy RBAC, tenant/facility/location isolation, audit history and financial redaction.
- Add the next migration revision after verified `0089`—normally `0090`, but do not assume if the graph changed.

Exclusions unless an existing approved specification explicitly requires them:

- Online medicine ordering or home delivery.
- Insurance/preauthorization.
- E-prescription exchange with external providers.
- New controlled-drug regulatory rules invented by the developer.
- Changes to accepted P30–P34 contracts unrelated to integration.

Acceptance:

- PostgreSQL tests for OTC eligibility, external prescription, controlled medicine denial/approval, FEFO, stock/billing atomicity, idempotency, concurrency, returns, RBAC and isolation.
- Frontend tests for search, cart, eligibility errors, external-prescription fields, confirmation, payment and receipt states.
- Chromium walk-in OTC sale and external-prescription sale flows.
- Regression of OPD prescription dispensing and Pharmacy P30–P34.

### RA-5 — Complete Release A automated gate

Build one deterministic Chromium chain using seeded test users and data:

1. Reception registers/selects the patient and books/checks in an appointment.
2. Appointment capacity and concurrent booking protection are proven.
3. Nurse records pre-vitals and hands off to Doctor.
4. Doctor completes consultation, controlled diagnosis, medicines and Lab orders.
5. Lab Technician collects, processes, records and verifies results.
6. Billing receives correct charges and validates payment/webhook idempotency and tamper/replay protection.
7. Pharmacy dispenses the OPD prescription and stock/ledger/invoice results are verified.
8. Hospital Admin verifies Nurse Roster, operational records and authorized reports.
9. Separate Chromium scenarios validate OTC and external-prescription dispensing.
10. Negative scenarios prove Super Admin tenant denial, role denial and cross-tenant/facility isolation.

The test must fail on any skipped business step, unexpected API error, console error relevant to the application, or incorrect persisted transaction.

### RA-6 — CI and complete regression

Repository-owner action:

- Configure `CI_POSTGRES_PASSWORD` and `CI_SECRET_KEY` in GitHub Actions secrets using strong non-production values.
- Do not place secret values in source, workflow defaults, logs or documentation.

Required green checks at the final HEAD:

- Sole migration head and clean fresh upgrade.
- Required downgrade/upgrade boundary validation.
- All configured schemas at the sole head.
- Complete PostgreSQL-backed backend suite with zero failures.
- TypeScript, ESLint, complete frontend unit suite and production build.
- Complete Playwright/Chromium suite, including RA-5.
- Docker Compose health validation.
- Backup/restore validation.
- Credential-leak and committed-secret scan.

Do not classify a failure as transient without reproducing the full suite successfully at the same HEAD.

### RA-7 — Hospital business UAT and release decision

Run UAT with named representatives for:

- Reception
- Nurse
- Doctor
- Pharmacy
- Lab
- Billing
- Hospital Admin
- Super Admin

Record each scenario with tester, date, environment, input, expected result, actual result, evidence and finding ID. Classify findings as:

- P0: safety, security, data corruption, financial integrity or release-blocking failure.
- P1: core workflow cannot be completed or has no acceptable workaround.
- P2: important defect with a safe workaround.
- P3: cosmetic, usability or documentation improvement.

Exit criteria:

- No open P0 or P1 findings.
- P2/P3 findings are fixed or explicitly accepted by the authorized business owner with target dates.
- Release notes include migrations, features, security changes, known limitations, deployment, rollback boundary, backup/restore and UAT evidence.
- Authorized Hospital business owner and technical owner record the OPD Core v1 sign-off decision.

## Status vocabulary

Use only these decisions:

- **NOT READY** — a mandatory technical or security requirement is absent or failing.
- **READY FOR INTERNAL DEMONSTRATION** — partial workflows can be shown, but UAT gates remain open.
- **READY FOR CONTROLLED HOSPITAL UAT** — RA-1 through RA-6 are completely green; business UAT may begin.
- **OPD CORE V1 SIGN-OFF READY** — RA-7 exit criteria are satisfied.

Automated tests alone must not close a required real-role UI verification. A failed or skipped CI gate must be reported explicitly.

## Required final completion report

Report:

1. Branch and exact HEAD before/after.
2. Repository and database migration heads before/after.
3. Files changed and migration revisions added.
4. Completion status for every RA task and acceptance criterion.
5. RBAC and tenant/facility/location-isolation evidence.
6. Exact commands and results for backend, frontend, migrations, Docker, Playwright and backup/restore.
7. GitHub Actions run URL and conclusion.
8. UAT findings by severity and disposition.
9. Skips, warnings, limitations and external owner actions.
10. Confirmation that no credentials or patient data were committed or logged.
11. Final decision using the status vocabulary above.

## Start instruction to the coding agent

Begin with a read-only repository audit. Map existing code and tests against RA-1 through RA-7 and produce a gap table. Do not modify files until the baseline, migration graph, dependencies and contracts are confirmed. If the requirements are internally consistent, implement the mandatory gaps in numbered order and stop at any unresolved business-rule ambiguity. Do not commit or push without explicit authorization.
