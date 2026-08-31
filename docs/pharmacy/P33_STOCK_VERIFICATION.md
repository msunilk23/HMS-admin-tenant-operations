# P33 - Implementation And Acceptance Evidence

**Canonical contract:** [P33_STOCK_COUNT_SPECIFICATION.md](P33_STOCK_COUNT_SPECIFICATION.md)

This report records P33 implementation, migration, verification, defects, and the final acceptance recommendation. It does not redefine the approved business or technical contract.

## Decision

**P33 ACCEPT**

The complete P33 vertical slice is implemented at migration `0087`. All mandatory migration, PostgreSQL, backend, frontend, deterministic-fixture, and Chromium gates passed. No critical or high P33 defect remains.

Validation date: 2026-08-31

## Delivered Scope

- Single-location `FULL`, `PARTIAL`, and `SAMPLE` stock-count sessions.
- Atomic snapshot and inventory freeze on transition to `IN_PROGRESS`.
- Decimal-safe physical quantity, variance, tolerance, repeated, high-value, zero, and unexpected-stock classification.
- Immutable original observations with separate assigned recount attempts and a two-recount limit.
- Maker-checker approval followed by a distinct adjustment-application action.
- Signed `ADJUSTMENT_IN` and `ADJUSTMENT_OUT` stock-ledger entries with count correlation.
- Transactional balance changes, audit records, freeze release, replay protection, and complete rollback.
- Tenant/facility/location isolation, backend permission enforcement, and authenticated facility scope.
- Role-protected React workflow with duplicate-submission prevention and deterministic Chromium coverage.

## Implementation Manifest

Database and backend:

- `backend/alembic/versions/0087_p33_stock_count.py`
- `backend/app/api/v1/p33.py`
- `backend/app/api/v1/pharmacy.py`
- `backend/app/api/v1/router.py`
- `backend/app/models/tenant/__init__.py`
- `backend/app/models/tenant/inventory_batch.py`
- `backend/app/models/tenant/p31_p34.py`
- `backend/app/schemas/p33.py`
- `backend/app/services/p33_service.py`
- `backend/app/services/inventory_service.py`
- `backend/app/services/pharmacy_dispensing.py`
- `backend/app/services/p32_service.py`
- `backend/app/services/stock_ledger_service.py`

Tests and deterministic data:

- `backend/tests/test_p33_acceptance.py`
- `backend/tests/test_p31_p34_comprehensive.py`
- `backend/tests/e2e_seed_task7.py`
- `frontend/e2e/pharmacy-p33-stock-count.spec.ts`
- `frontend/src/features/pharmacy/InventoryCountPage.test.tsx`

Frontend:

- `frontend/src/features/pharmacy/InventoryCountPage.tsx`
- `frontend/src/services/p33Service.ts`
- `frontend/src/App.tsx`
- `frontend/src/components/shared/Layout.tsx`

## Contract Evidence

### Persistence And Migration

- `0086` was confirmed as the sole parent before P33 implementation.
- `0087` creates the six P33 workflow/settings/idempotency tables, constraints, indexes, inventory freeze columns, and the eight permission codes.
- Permission seed matches the approved role matrix: pharmacists and store managers operate counts; only store managers approve/apply; hospital admins and auditors are view-only.
- The lifecycle command ran `heads`, `current`, `downgrade 0086`, `current`, `upgrade 0087`, `current`, and `heads` against the configured PostgreSQL database.
- All seven configured tenant schemas completed `0087 -> 0086 -> 0087`; the repository and database ended at the single head `0087`.

### Workflow And Integrity

- Snapshot quantity is `available + reserved`; the exact batch, medicine, location, tenant, and facility are retained.
- Starting is locked and idempotent. A concurrent duplicate start creates one detail snapshot and one operation record.
- Every mutating route requires `Idempotency-Key`; identical replay returns the stored result and changed payload returns `409`.
- Detail writes use optimistic versions and reject stale updates.
- `FULL` captures all active location batches; `PARTIAL` and `SAMPLE` require immutable explicit selections. All types require every scoped line before submission.
- Illegal starts, edits outside `IN_PROGRESS`, illegal approvals/applications, post-submission pharmacist cancellation, and a third recount are rejected.
- Original count details remain unchanged by recount values. Recount assignee, recorder, attempt, and effective totals persist separately.

### Security And Isolation

- All P33 routes use the corresponding `INVENTORY_COUNT_*` backend permission dependency.
- Tenant and facility derive from authenticated context; client-supplied scope cannot override either value.
- PostgreSQL tests prove cross-tenant and cross-facility mutations return not found.
- Chromium proves an unpermitted receptionist cannot enter the P33 route or create state.
- Maker-checker blocks initiators, original recorders/completers, recount assignees, and recount recorders from approval; recount participants also cannot apply.

### Freeze, Drift, And Rollback

- Count start freezes every scoped inventory row in the same transaction as snapshot creation.
- Dispensing, balance synchronization, transfer/receipt/return ledger paths, quarantine/disposal, recall reservation mutation, and adjustment paths reject frozen rows.
- Approval and application lock rows and compare current available/reserved values with the snapshot.
- Snapshot drift returns `409`, leaves the count submitted, and persists a `SNAPSHOT_DRIFT` audit event after rollback of the failed action.
- Cancellation and successful application release the freeze; intermediate states retain it.
- Reservation protection rejects a shortage below reserved stock.
- Forced multi-line application failure proves no partial balance, ledger, status, or freeze mutation is committed.

### Classification And Ledger

- PostgreSQL boundary tests cover `ZERO`, positive, negative, `WITHIN_TOLERANCE`, `OUTSIDE_TOLERANCE`, `HIGH_VALUE`, `REPEATED`, and `UNEXPECTED_STOCK`.
- A tolerated nonzero variance still writes an adjustment.
- Zero variance writes no ledger row.
- Positive variances write positive `ADJUSTMENT_IN`; shortages write negative `ADJUSTMENT_OUT`.
- Approval creates no ledger movement. Explicit application writes each nonzero movement once, updates balances, records audit/operation evidence, and releases the freeze.
- Replaying application creates no duplicate balance, ledger, operation, or audit effects.

## Verification Results

Migration lifecycle:

```text
python tests/e2e_seed_task7.py cleanup
python -m alembic heads
python -m alembic current
python -m alembic downgrade 0086
python -m alembic current
python -m alembic upgrade 0087
python -m alembic current
python -m alembic heads
Result: PASS; seven tenant schemas round-tripped; sole head/current 0087
```

Focused PostgreSQL P33 acceptance after the final coverage expansion:

```text
python -m pytest tests/test_p33_acceptance.py -q
Result: 10 passed, 1 warning in 18.80s
```

Focused P33 compatibility plus acceptance:

```text
python -m pytest tests/test_p31_p34_comprehensive.py::TestP33StockCount tests/test_p33_acceptance.py -q
Result before final three matrix tests: 9 passed, 10 warnings in 9.41s
```

P32/freeze integration regression:

```text
Focused P32, inventory, and P33 integration selection
Result: 18 passed
```

Definitive full PostgreSQL backend regression, rerun after all test changes:

```text
python -m pytest tests -q
Result: 367 passed, 291 warnings in 172.31s
```

Frontend gates, rerun from the final corrected state:

```text
npm run type-check
Result: PASS

npm run lint
Result: PASS

npm run test:unit
Result: 7 files passed; 32 tests passed

npm run build
Result: PASS; 2061 modules transformed; built in 6.00s
```

Deterministic Chromium gate:

```text
npx playwright test e2e/pharmacy-p33-stock-count.spec.ts --project=chromium --workers=1
Result: 3 passed in 51.5s; no skipped or did-not-run cases
```

The Chromium scenarios prove the principal count/approve/apply path and signed persisted ledger, denied role, one-request duplicate suppression, assigned recount, and immutable original observation.

## Defects Resolved During Acceptance

- Replaced preliminary `INITIATED`/reversed-variance assumptions with the canonical statuses and `physical - system` formula.
- Prevented async ORM timestamp serialization from triggering `MissingGreenlet`.
- Added synchronous frontend submission locks for same-tick duplicate clicks.
- Removed client-controlled facility scope from inventory-batch lookup.
- Made deterministic P33 reset foreign-key safe.
- Added missing freeze checks to direct balance synchronization and recall reservation mutation.
- Preserved original detail classifications and values during recount resubmission.
- Added unexpected-stock workflow and complete application rollback evidence.
- Added participant-aware maker-checker frontend controls and pharmacist cancellation visibility rules.
- Closed explicit acceptance gaps for `FULL`/`SAMPLE`, facility isolation, transition legality, classification boundaries, ledger directions, and drift-audit persistence.

## Residual Risk And Warnings

- The full suite reports existing deprecation warnings and SQLAlchemy metadata sort warnings for the pre-existing invoice/dispense foreign-key cycle. No warning is a P33 failure.
- The frontend build reports an existing bundle-size advisory for the main chunk. Build output is valid and the advisory does not affect P33 correctness.
- Browser coverage is intentionally the required critical-path set; exhaustive visual permutations remain component/service-test territory.

## Final Recommendation

All canonical acceptance conditions are satisfied. P33 may proceed as the accepted Pharmacy baseline. Do not begin P34 until separately authorized.

**P33 ACCEPT**
