# Pharmacy P33 — Stock Count and Variance Adjustment Specification

## 1. Document status

- **Status:** Approved contract amendment for implementation
- **Phase:** Pharmacy P33
- **Baseline branch:** `feature/pharmacy-module`
- **Expected previous migration head:** `0086`
- **Proposed P33 migration:** `0087`, subject to confirming that `0086` remains the single Alembic head
- **Supersedes:** Conflicting preliminary P33 model assumptions, mock-only tests, and contradictory master-plan statements

This document is the detailed source of truth for P33. The Pharmacy master plan should summarize and link to it.

## 2. Objective

P33 provides controlled physical stock counting for a pharmacy location, variance review, recount, maker-checker approval, and transactional application of approved inventory adjustments.

P33 covers the complete backend, frontend, database migration, permissions, audit, deterministic test data, PostgreSQL acceptance tests, and Chromium workflow.

## 3. Scope boundaries

### Included

- Single-location stock-count sessions
- `FULL`, `PARTIAL`, and `SAMPLE` counts
- Snapshot of system quantities
- Scoped inventory freeze while counting
- Physical quantity recording
- Variance calculation and classification
- Recount assignment and submission
- Maker-checker approval
- Explicit application of approved adjustments
- Inventory balance, stock-ledger, and audit integration
- Tenant and facility isolation
- Idempotency and concurrency protection

### Excluded

- Multi-location count sessions
- Parent count campaigns spanning multiple locations
- System-generated random sampling
- Quarantine inventory counting
- P34 and Lab functionality

## 4. Canonical variance formula

```text
variance_quantity = physical_quantity - system_quantity
```

| Result | Meaning | Adjustment |
|---|---|---|
| Positive | Physical stock exceeds system stock | `ADJUSTMENT_IN` |
| Negative | Physical stock is below system stock | `ADJUSTMENT_OUT` |
| Zero | Physical and system stock agree | No adjustment |

Example:

```text
System quantity   = 100
Physical quantity = 95
Variance quantity = 95 - 100 = -5
```

The preliminary test expectation of `-5` is consistent with this formula. Any master-plan statement defining variance as `system - physical` must be corrected.

## 5. Count scope

Each stock-count session belongs to exactly one:

- Tenant
- Facility
- Pharmacy location

The initiation contract accepts one `pharmacy_location_id`. Multiple locations require separate stock-count sessions.

Every detail is identified within the session by medicine and batch. Duplicate medicine/batch details are prohibited.

## 6. Count types

### 6.1 `FULL`

- Includes every active, non-disposed inventory batch in the selected location.
- Completion requires a physical quantity for every generated detail.
- An unexpected physical batch may be added with supporting evidence and must be highlighted during approval.

### 6.2 `PARTIAL`

- The initiator supplies an explicit medicine or batch list.
- At least one selection is required.
- The selection becomes immutable when counting starts.
- Completion requires every selected detail to be counted.

### 6.3 `SAMPLE`

- The initiator supplies the sample medicine or batch list.
- P33 does not randomly generate a sample.
- At least one selection is required.
- Completion requires every sampled detail to be counted.

## 7. Canonical statuses and transitions

Statuses:

```text
CREATED
IN_PROGRESS
SUBMITTED
RECOUNT_REQUIRED
RECOUNT_IN_PROGRESS
RESUBMITTED
APPROVED
APPLIED
CANCELLED
```

Allowed transitions:

| Current status | Allowed next status |
|---|---|
| `CREATED` | `IN_PROGRESS`, `CANCELLED` |
| `IN_PROGRESS` | `SUBMITTED`, `CANCELLED` |
| `SUBMITTED` | `APPROVED`, `RECOUNT_REQUIRED`, `CANCELLED` |
| `RECOUNT_REQUIRED` | `RECOUNT_IN_PROGRESS`, `CANCELLED` |
| `RECOUNT_IN_PROGRESS` | `RESUBMITTED`, `CANCELLED` |
| `RESUBMITTED` | `APPROVED`, `RECOUNT_REQUIRED`, `CANCELLED` |
| `APPROVED` | `APPLIED` |
| `APPLIED` | Terminal |
| `CANCELLED` | Terminal |

Rules:

- The initial status is `CREATED`; `INITIATED` is not a P33 status.
- Approved counts cannot be edited.
- Applying adjustments is a separate explicit action after approval.
- Cancellation requires a reason.
- A maximum of two recounts is permitted.
- After the second recount, the approver must approve or cancel; requesting another recount is forbidden.

## 8. System quantity definition

`system_quantity` is the physical on-hand quantity recorded for the exact combination of:

```text
tenant + facility + pharmacy location + medicine + batch
```

It includes reserved stock because reserved medicine remains physically present. It excludes:

- Disposed stock
- Stock transferred out
- Stock in transit
- Quarantined stock, unless a future workflow explicitly counts a quarantine bucket

The count snapshot stores:

```text
system_quantity
reserved_quantity
available_quantity
```

Required invariant:

```text
system_quantity = available_quantity + reserved_quantity
```

An adjustment must never produce `system_quantity < reserved_quantity`. If a shortage would violate this invariant, applying the adjustment must return a conflict and require reservation resolution.

## 9. Snapshot and concurrent movement policy

P33 uses a scoped inventory freeze.

- `CREATED` does not freeze inventory.
- Transition to `IN_PROGRESS` atomically captures the snapshot and freezes every batch in the count scope.
- Dispensing, receipt, transfer, return, quarantine, release, disposal, or another adjustment affecting a frozen inventory row must return `409 Conflict`.
- The freeze remains until the session becomes `APPLIED` or `CANCELLED`.
- Approval and application must verify that current balances still equal the captured snapshot.
- Unexpected drift blocks approval/application and creates an audit event.
- Backend transactions and row locks must enforce the freeze; frontend control visibility is not sufficient.

Starting a count, capturing its details, and activating its freeze must be one transaction.

## 10. Variance thresholds and classifications

Default thresholds must be tenant-configurable.

| Rule | Default |
|---|---:|
| Quantity tolerance | `±0.5%` |
| Repeated-variance lookback | `90 days` |
| Repeated-variance trigger | Same medicine/batch varied in two prior completed counts |
| High-value variance | Absolute variance value of at least `₹5,000` |

Variance percentage:

```text
abs(variance_quantity) / system_quantity * 100
```

Special handling:

- If system and physical quantities are both zero, variance percentage is zero.
- If system quantity is zero and physical quantity is nonzero, classify it as unexpected stock; do not report zero percent.

Variance value:

```text
abs(variance_quantity) * batch_unit_cost
```

Use the immutable GRN/batch unit acquisition cost. Missing cost must block approval instead of treating the value as zero.

Required classifications:

```text
ZERO
WITHIN_TOLERANCE
OUTSIDE_TOLERANCE
HIGH_VALUE
REPEATED
UNEXPECTED_STOCK
```

A detail may have multiple flags. Tolerance is a classification only: it does not change physical quantity and does not suppress a real nonzero adjustment.

## 11. Recount rules

- An approver may request a recount from `SUBMITTED` or `RESUBMITTED`.
- A recount request requires a reason and an assigned counter.
- The assigned recount user must differ from the original counter.
- The assignee accepts/starts the recount, moving it to `RECOUNT_IN_PROGRESS`.
- Recount values must be stored separately from original values so the audit history remains immutable.
- Resubmission recalculates the effective variance from the latest recount value.
- No more than two recount attempts are permitted.

## 12. Permissions and default role matrix

Permissions:

```text
INVENTORY_COUNT_VIEW
INVENTORY_COUNT_INITIATE
INVENTORY_COUNT_RECORD
INVENTORY_COUNT_COMPLETE
INVENTORY_COUNT_RECOUNT
INVENTORY_COUNT_APPROVE
INVENTORY_COUNT_APPLY
INVENTORY_COUNT_CANCEL
```

| Role | View | Initiate | Record | Complete | Recount | Approve | Apply | Cancel |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Pharmacist | Yes | Yes | Yes | Yes | Assigned only | No | No | Before submission |
| Pharmacy Manager | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Tenant Admin | Yes | No | No | No | No | No | No | No |
| Auditor | Yes | No | No | No | No | No | No | No |

RBAC must be enforced by the backend for every endpoint and record.

## 13. Maker-checker separation

- The initiator may also be the original counter.
- Anyone who initiated, recorded, or completed the count cannot approve it.
- The approver may apply the already-approved adjustment.
- The recount assignee must differ from the original counter.
- Anyone who performs a recount cannot approve or apply that count.
- Permission assignment does not override maker-checker separation.

## 14. Idempotency

The `Idempotency-Key` request header is mandatory for every mutating workflow action:

- Initiate
- Start counting
- Complete/submit
- Request recount
- Start recount
- Resubmit recount
- Approve
- Apply adjustment
- Cancel

Semantics:

- Scope the key by tenant, authenticated user, endpoint/action, and count where applicable.
- Repeating the same key with an identical payload returns the original status and response.
- Repeating the same key with a different payload returns `409 Conflict`.
- A failed or rolled-back attempt is not stored as a successful result.
- Concurrent calls with the same key cause one mutation only.
- Replaying application of adjustments cannot duplicate balance changes, ledger entries, or audit events.

Individual count-detail updates must also use optimistic versioning to prevent lost updates.

## 15. Approval and adjustment application

Approval:

- Validates status, permissions, maker-checker rules, cost availability, snapshot consistency, and all required detail counts.
- Records the approval decision and audit event.
- Does not change inventory balances or create stock-ledger movements.

Application:

- Processes every approved nonzero variance exactly once.
- Updates inventory balances.
- Creates stock-ledger records.
- Writes audit records.
- Releases the inventory freeze.
- Moves the session to `APPLIED`.
- Performs all effects in one transaction and rolls back completely on failure.

Zero variances create no stock-ledger entry. Nonzero variances within tolerance still require an adjustment.

## 16. Ledger convention

```text
variance > 0:
  movement_type = ADJUSTMENT_IN
  signed_quantity = positive variance

variance < 0:
  movement_type = ADJUSTMENT_OUT
  signed_quantity = negative variance
```

Each adjustment ledger entry must reference:

- Stock-count ID
- Count-detail ID
- Tenant, facility, and pharmacy location
- Medicine and batch
- System snapshot quantity
- Physical quantity
- Variance quantity
- Unit cost and variance value
- Approver
- Applying user
- Reason
- Timestamp

The implementation must remain compatible with established immutable stock-ledger conventions. If the existing ledger stores outbound movement magnitude rather than a signed negative quantity, preserve that storage convention while exposing the canonical signed variance in the P33 API and document the mapping before implementation.

## 17. Data integrity and security

The implementation must provide:

- Tenant and facility isolation on all reads and mutations
- Location ownership validation
- Database uniqueness constraints for session details and idempotency records
- Row locking for inventory and workflow state transitions
- Decimal-safe quantities and monetary values
- Explicit illegal-transition errors
- Immutable original count and recount history
- Append-only audit and stock-ledger records
- Complete transaction rollback on any failure
- Prevention of duplicate adjustment application

Client-supplied tenant or facility identifiers must never override authenticated scope.

## 18. Required API capabilities

The exact routes should follow existing Pharmacy conventions, but P33 must expose capabilities for:

- Create a count
- List and filter counts
- Read count header, details, classifications, history, and assignments
- Start counting and capture snapshot
- Record/update physical quantities
- Submit the count
- Request and assign recount
- Start and record recount
- Resubmit recount
- Approve the count
- Apply approved adjustments
- Cancel the count
- List/filter variances, including tolerance, repeated, high-value, and unexpected-stock flags

All list endpoints require pagination and tenant/facility isolation.

## 19. Frontend requirements

Provide a role-protected P33 workflow with:

- Count list and filters
- Initiation form for location and count type
- Explicit item selection for `PARTIAL` and `SAMPLE`
- Count detail entry with system snapshot, physical quantity, variance, flags, and notes
- Completion validation
- Recount request, assignment, entry, and resubmission
- Maker-checker approval view
- Separate adjustment-application confirmation
- Audit/history view
- Loading, empty, validation, forbidden, conflict, success, and server-error states
- Duplicate-submission prevention
- Refresh/reload consistency
- Accessible labels and keyboard-operable controls

## 20. Acceptance testing

P33 acceptance requires all of the following:

1. Focused backend service/API tests.
2. Real PostgreSQL acceptance tests.
3. Permission and denied-role tests.
4. Cross-tenant and cross-facility isolation tests.
5. Legal and illegal transition tests.
6. Full, partial, and sample completion-rule tests.
7. Recount assignment, limit, history, and separation tests.
8. Threshold and classification tests.
9. Inventory-freeze and concurrent-movement tests.
10. Snapshot-drift detection tests.
11. Idempotency replay and payload-conflict tests.
12. Concurrent duplicate-action tests.
13. Maker-checker tests.
14. Zero, positive, negative, tolerated, repeated, high-value, and unexpected-stock variance tests.
15. Ledger direction and signed-quantity tests.
16. Reservation-invariant tests.
17. Rollback tests proving no partial balance, ledger, audit, status, or freeze changes.
18. Migration upgrade, downgrade, and re-upgrade lifecycle.
19. Pharmacy backend regression.
20. Mandatory full backend regression.
21. Frontend type-check, ESLint, complete unit suite, and production build.
22. Deterministic P33 E2E seed/reset.
23. Chromium coverage for the principal success path and critical permission, conflict, recount, and concurrency paths.

Tests must not weaken assertions, bypass production validation, depend on expiring fixed dates, or treat skipped/did-not-run Chromium tests as acceptance.

## 21. Acceptance decision

Recommend **P33 ACCEPT** only when:

- The complete approved contract is implemented.
- Migration `0087` is validated and remains a single linear head.
- Focused and PostgreSQL acceptance tests pass.
- Pharmacy and full backend regressions pass with exit code `0`.
- Frontend type-check, lint, unit tests, and production build pass.
- All required Chromium tests run and pass with no skipped or did-not-run cases.
- RBAC, isolation, maker-checker, idempotency, concurrency, freeze, recount, ledger, audit, reservation protection, and rollback are verified.
- No critical or high P33 defect remains.

Otherwise, recommend **P33 NOT ACCEPTED**, report the exact blockers, and do not begin P34.

## 22. Implementation controls

- Confirm `0086` is still the sole migration head before creating `0087`.
- Update the Pharmacy master plan to link to this specification.
- Correct preliminary P33 models/tests that conflict with this contract; P33 has not been accepted or released, so no compatibility with `INITIATED` or the reversed variance formula is required.
- Preserve all unrelated staged, unstaged, and untracked user changes.
- Do not commit, merge, push, deploy, rebase, reset, stash, clean, begin P34, or perform Lab work.
- Stop after producing the P33 acceptance report and wait for approval.
