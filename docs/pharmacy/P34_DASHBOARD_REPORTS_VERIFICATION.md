# P34 Pharmacy Dashboard, Alerts, Reports and Exports Verification

## Decision

**Accepted.** The P34 implementation satisfies the canonical contract in `P34_DASHBOARD_REPORTS_SPECIFICATION.md`. The Pharmacy dashboard is an additive, separately authorized workflow. The existing general HMS dashboard production route, API, cards, and implementation remain unchanged.

## Architecture separation

| Concern | General HMS dashboard | Pharmacy P34 dashboard |
|---|---|---|
| Frontend route | `/dashboard` | `/pharmacy/dashboard` |
| Backend API | `/api/v1/admin/stats` | `/api/v1/pharmacy-dashboard` |
| Frontend owner | `frontend/src/features/admin/AdminDashboard.tsx` | `frontend/src/features/pharmacy/PharmacyDashboardPage.tsx` |
| Backend owner | `backend/app/api/v1/admin.py` | `backend/app/api/v1/pharmacy_dashboard.py` |
| Primary permission | Existing general-dashboard authorization | `PHARMACY_DASHBOARD_VIEW` |

A final Git diff check returned no changes for either general-dashboard production file:

```text
backend/app/api/v1/admin.py
frontend/src/features/admin/AdminDashboard.tsx
```

The explicit Chromium regression verifies that `/dashboard` still displays `Command Center` and the established general-dashboard cards, does not display the Pharmacy Dashboard heading, and preserves existing authorization behavior.

## Delivered implementation

### Backend

- Alembic migration `0088` adds the seven P34 permissions and canonical alert, acknowledgement, configuration, and operation tables.
- The migration replaces preliminary P34 tables in dependency order and supports downgrade/upgrade across all configured tenant schemas.
- Canonical tenant models store tenant, facility, and optional Pharmacy-location scope.
- Dedicated schemas define dashboard, report, alert, configuration, capability, pagination, and metadata contracts.
- The Pharmacy dashboard service owns business-date handling, card formulas, 16 reports, stable pagination, report filters, inventory movement classification, alert evaluation, deduplication, resolution, and recurrence.
- The dedicated API exposes capabilities, dashboard cards, report catalogue/results/CSV export, alerts, authorized recalculation, acknowledgement, and versioned configuration.
- Permission helper overloads document its existing dependency-factory and direct-check modes; Pylance reports no errors in the P34 API or helper.

### Frontend

- `/pharmacy/dashboard` is registered independently of `/dashboard`.
- `PermissionGuard` prevents unauthorized users from loading Pharmacy dashboard data and redirects them to the unchanged general dashboard.
- Sidebar visibility is based on live backend capabilities rather than a narrower frontend role list.
- The dedicated page provides Overview, Reports, Alerts, and Configuration views.
- Dashboard cards drill into matching reports; report filters, pagination, CSV export, alert acknowledgement notes, and optimistic configuration versioning are implemented.
- The typed client models operational-only financial redaction with nullable valuation fields.

### Deterministic fixtures and tests

- The P34 browser fixture resets and seeds a stable facility-scoped Pharmacy scenario.
- A fixture snapshot supports deterministic browser assertions.
- Real PostgreSQL acceptance covers timezone boundaries, facility isolation, redaction, report filtering, movement classification, alerts, mutation idempotency, optimistic conflicts, acknowledgement immutability, and CSV formula-injection protection.

## Authorization and isolation evidence

- Tenant ID is derived from the authenticated JWT and tenant schema context.
- Facility ID is derived from authenticated context; no request query, header, or body can override it.
- Optional `pharmacy_location_id` values are validated against the authenticated tenant and facility.
- Backend permissions are authoritative for every protected P34 endpoint.
- Pharmacists receive operational dashboard data but financial valuation fields are redacted by the backend.
- Pharmacist requests for sales/payment, inventory-valuation, and audit reports return `403`.
- Audit report rows require `PHARMACY_AUDIT_VIEW` and are filtered by embedded authenticated facility/location metadata.
- Export, acknowledgement, configuration, and recalculation actions create audit events.
- Mutation idempotency is checked both before and after row locking; reused keys with changed payloads and stale versions are rejected.

## Functional evidence

The dashboard implements all required operational and financial card groups, including sales, pending prescriptions, dispensing, posted GRNs, patient and supplier returns, adjustments, stock alerts, expiry buckets, valuation, and outside purchases.

The report catalogue contains all 16 required reports. Results include applied filters, business timezone/date range, pagination metadata, and relevant currency grouping. Supported filters include date, location, medicine, batch, supplier, status, and alert type. Movement classification uses deterministic medicine-ID tie-breaking.

Alert recalculation supports `LOW_STOCK`, `OUT_OF_STOCK`, `EXPIRY`, `UNUSUAL_ADJUSTMENT`, `REPEATED_VARIANCE`, and `UNUSUAL_RETURN`. It updates matching active alerts, resolves cleared conditions, and links recurrent conditions to the prior resolved alert. Acknowledgements require notes and do not mutate stock or resolve the underlying condition.

CSV export is authenticated, capped at 10,000 rows, records scope metadata and an audit event, and neutralizes spreadsheet formula prefixes.

## Verification results

### Final backend and migration gate

Executed from `backend` against PostgreSQL on port 5433:

```powershell
python -m alembic downgrade 0087
python -m alembic upgrade 0088
python -m alembic downgrade 0087
python -m alembic upgrade head
python -m alembic current
python -m pytest tests -q
```

Result:

```text
All seven configured schemas: 0088 (head)
371 passed, 295 warnings in 229.09s
```

The two legacy-schema migration cases that exposed preliminary-table dependency order were rerun directly after the migration repair:

```text
2 passed in 44.50s
```

The final permission typing repair was validated with Pylance diagnostics and the focused PostgreSQL suite:

```text
Pylance: no errors in core/dependencies.py or pharmacy_dashboard.py
4 passed, 1 warning in 10.03s
```

### Focused backend gates

```text
P34 real PostgreSQL acceptance: 4 passed
P31-P34 legacy model regression: 11 passed
```

### Frontend gates

```text
Focused Pharmacy dashboard components: 3 passed
Complete Vitest suite: 35 passed
ESLint: passed
TypeScript no-emit check: passed
Production build: passed
```

### Chromium acceptance

```text
Pharmacy P34 dashboard plus general-dashboard regression: 6 passed
```

Covered scenarios:

- Separate operational Pharmacy dashboard and report drilldown
- Persisted alert acknowledgement
- Authorized administrator export and configuration
- Permission denial before dashboard data loading
- Existing general-dashboard rendering and card regression
- Existing general-dashboard authorization behavior

## Non-blocking warnings and residual limits

- The backend suite reports existing Pydantic V1 compatibility deprecations, `datetime.utcnow()` deprecations, and SQLAlchemy metadata-sort warnings caused by the pre-existing cyclic relationship between `invoices` and `pharmacy_dispenses`.
- The frontend production build reports the existing bundle-size advisory. It does not fail the build.
- P34 intentionally supports synchronous CSV only, capped at 10,000 rows. PDF, XLSX, asynchronous export jobs, predictive analytics, and controlled-drug regulatory reports remain outside P34 scope.
- P34 does not add Pharmacy cards to or redesign the general HMS dashboard.

## Acceptance conclusion

P34 is release-ready against the approved specification. Migration `0088` is reversible and at head for every configured schema; backend, frontend, PostgreSQL, and Chromium gates pass; authenticated tenant/facility boundaries are enforced server-side; and the existing general HMS dashboard remains intact and independently tested.
