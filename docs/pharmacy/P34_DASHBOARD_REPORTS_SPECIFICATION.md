# Pharmacy P34 — Dashboard, Alerts, Reports and Exports Specification

## 1. Document status

- **Status:** Approved canonical contract for implementation
- **Phase:** Pharmacy P34
- **Baseline branch:** `feature/pharmacy-module`
- **Expected previous migration head:** `0087`
- **Proposed P34 migration:** `0088`, subject to confirming that it remains unused and `0087` is the sole current head
- **Supersedes:** Conflicting preliminary P34 models, mock-only assertions, incomplete phase documents, and incompatible master-plan statements

This document is the authoritative business and technical contract for P34. `P34_DASHBOARD_REPORTS_VERIFICATION.md` is reserved for implementation and acceptance evidence. `P30_P34_MASTER_PLAN.md` must summarize and link to this specification.

## 2. Objective

P34 provides tenant- and facility-isolated Pharmacy dashboards, operational alerts, reports, and audited CSV exports.

P34 introduces a **separate Pharmacy dashboard**. It must not replace, repurpose, or overwrite the existing general HMS dashboard.

P34 is read-oriented except for:

- Alert acknowledgement
- Alert configuration
- Recording report-export audit events

P34 must not modify stock, invoices, payments, GRNs, returns, prescriptions, dispensing records, or accepted P30–P33 records.

## 2.1 Dashboard separation and integration

The application must retain two distinct dashboard contexts:

| Dashboard | Purpose | P34 impact |
|---|---|---|
| General HMS dashboard | Hospital-wide operational overview | Existing behaviour, routes, cards, APIs, permissions, and tests remain unchanged |
| Pharmacy dashboard | Pharmacy sales, dispensing, purchasing, inventory, alerts, valuation, and reports | New P34 workflow |

Requirements:

- Create a dedicated Pharmacy dashboard route using the repository's Pharmacy route convention, for example `/pharmacy/dashboard`.
- Use dedicated Pharmacy dashboard API endpoints, services, frontend components, navigation entries, permissions, and tests.
- Do not reuse the general dashboard route as the Pharmacy landing page.
- Do not rename, remove, replace, or change the meaning of existing general-dashboard cards or APIs.
- Pharmacy navigation should open the Pharmacy dashboard only for users with `PHARMACY_DASHBOARD_VIEW`.
- Users without Pharmacy dashboard permission must retain their existing general-dashboard experience.
- A future general-dashboard Pharmacy summary card may link to the Pharmacy dashboard, but adding or changing such a card is outside P34 unless an existing approved requirement explicitly mandates it.
- Shared visual components may be reused, but Pharmacy data loading, filters, permissions, and state must remain isolated from the general dashboard.
- Existing general-dashboard regression tests must remain green, and P34 must add an explicit regression proving that the general dashboard was not overwritten.

## 3. Scope

### 3.1 Included

- Pharmacy operational and financial dashboard cards
- Operational inventory alerts
- Alert acknowledgement and configuration
- Paginated reports
- Synchronous CSV exports
- Existing audit-log reporting and new P34 audit events
- Tenant, facility, and authorized pharmacy-location isolation
- RBAC, idempotency, optimistic versioning, concurrency protection, and rollback for P34 mutations
- Backend, frontend, migration, deterministic fixtures, PostgreSQL acceptance, and Chromium coverage

### 3.2 Excluded

- Controlled-drug regulatory reports
- Accounting journal generation
- Predictive forecasting
- Supplier-performance scoring
- PDF or XLSX exports
- Asynchronous report jobs
- Report-cache tables
- Cryptographic signing or hash chaining
- P35, Lab, or non-Pharmacy work
- Replacement or redesign of the existing general HMS dashboard
- Addition of Pharmacy cards to the general HMS dashboard unless separately approved

## 4. Required dashboard cards

| Card | Required measure |
|---|---|
| Today's sales | Gross, discount, tax, refund, and net-paid values |
| Prescriptions pending | Prescriptions waiting for Pharmacy action |
| Dispensed today | Completed dispensing count and quantity |
| Purchases/GRNs today | Posted GRN count and value |
| Patient returns today | Completed return count and refund value |
| Supplier returns today | Completed supplier-return count and value |
| Stock adjustments today | In/out count, quantity, and value |
| Low-stock items | Count of active low-stock alerts |
| Out-of-stock items | Count of active out-of-stock alerts |
| Expiring stock | Counts for 0–30, 31–60, and 61–90 days |
| Inventory valuation | Available, reserved, quarantined, and total physical values shown separately |
| Outside purchases | Prescription items recorded as purchased outside |

Cards must link to their corresponding filtered reports where applicable. Card responses must state the effective business date, timezone, currency grouping, facility, and optional location filter.

## 5. Required report catalogue

P34 must provide:

1. Sales and payment report
2. Dispensing report
3. Purchase and GRN report
4. Patient-return report
5. Supplier-return report
6. Outside-purchase report
7. Current-stock report
8. Inventory-valuation report
9. Low-stock, out-of-stock, and reorder report
10. Expiry report
11. Stock-ledger/movement report
12. Stock-adjustment report
13. Stock-count variance report using accepted P33 data
14. Fast-, slow-, and non-moving inventory report
15. Alert and acknowledgement report
16. Pharmacy audit report

Each report must expose its applied filters, business timezone, date range, pagination metadata, and currency grouping where relevant.

## 6. Isolation and authorization scope

Every dashboard card, query, report, export, alert, configuration record, and audit read is scoped by:

```text
authenticated tenant + authenticated/authorized facility
```

Rules:

- Tenant and facility are derived from authenticated context.
- Client headers, query parameters, or request bodies cannot override authenticated tenant or facility scope.
- `pharmacy_location_id` is an optional authorized filter.
- Without a location filter, results aggregate only locations the user may access within the authenticated facility.
- Unauthorized cross-tenant, cross-facility, and cross-location requests must follow established forbidden/not-found behaviour without disclosing record existence.
- Alert and configuration records must store tenant, facility, and applicable pharmacy-location scope.
- Preliminary alert models without facility/location scope must be corrected.

## 7. Business date, timezone, currency, and numeric rules

Resolve timezone in this order:

1. Facility timezone
2. Tenant timezone when facility timezone is absent
3. UTC only as the final fallback

“Today” means the local business date in the resolved timezone.

All quantities and monetary values must use Decimal-safe handling. Do not aggregate different currencies into one number. When multiple currencies exist, return separate totals by currency.

## 8. Financial definitions

Expose financial measures separately:

```text
gross_sales = sum of posted invoice-line gross amounts
discount    = sum of posted invoice discounts
tax         = sum of posted invoice taxes
invoice_net = gross_sales - discount + tax
refunds     = sum of completed patient-refund amounts
net_paid    = successful allocated payments - completed refunds
```

Rules:

- Exclude draft, cancelled, failed, and voided transactions.
- Payment date determines “paid today.”
- Invoice date determines “invoiced today.”
- Refund completion date determines “refunded today.”
- Invoice status alone is not proof of payment.
- Dashboard and reports must expose invoiced and paid figures separately.
- Refunds must not be subtracted twice when an upstream aggregate already stores a net value.

## 9. Inventory valuation

Use immutable batch acquisition unit cost:

```text
inventory_value = quantity × batch_unit_cost
```

Report separately:

- Available value
- Reserved value
- Quarantined value
- Total physical value

Do not include disposed or transferred-out stock. Stock in transit must be reported separately if present and must not be included in location physical value. Missing acquisition cost must be returned as `unvalued`; it must not be silently valued at zero.

## 10. Movement classifications

Default definitions:

- **Fast-moving:** top 20% by dispensed quantity during the last 30 completed business days.
- **Slow-moving:** bottom 20% among items with at least one dispensing movement during the last 90 completed business days.
- **Non-moving:** current stock exists but no dispensing movement occurred during the last 90 completed business days.

Every classification response must include:

- Calculation window
- Dispensed/movement quantity
- Current inventory quantity
- Inventory value
- Applied facility and location scope

Ranking ties must be handled deterministically using the established medicine identifier as the final sort key.

## 11. Alert types and default rules

Required alert types:

```text
LOW_STOCK
OUT_OF_STOCK
EXPIRY
UNUSUAL_ADJUSTMENT
REPEATED_VARIANCE
UNUSUAL_RETURN
```

| Alert | Default rule |
|---|---|
| `OUT_OF_STOCK` | Available quantity `<= 0` |
| `LOW_STOCK` | Available quantity `<=` configured location reorder level and `> 0` |
| `EXPIRY` | Positive physical quantity expires within 90 days |
| `UNUSUAL_ADJUSTMENT` | Absolute adjustment value `>= ₹5,000` or absolute quantity change `>= 10%` of pre-adjustment on-hand |
| `REPEATED_VARIANCE` | Same location/medicine/batch varied in two prior applied P33 counts within 90 days |
| `UNUSUAL_RETURN` | Completed return value `>= ₹5,000` or returned quantity `>= 10%` of original dispensed quantity |

Thresholds must be configurable. Currency-specific monetary thresholds use the tenant’s configured threshold for that currency; the ₹5,000 value is the INR default, not a cross-currency conversion rule.

Expiry buckets:

```text
0–30 days
31–60 days
61–90 days
```

Expired stock with remaining quantity stays in the critical 0–30 bucket and must also be visibly marked `EXPIRED`.

## 12. Alert lifecycle and deduplication

Statuses:

```text
OPEN
ACKNOWLEDGED
RESOLVED
```

Rules:

- Only one active alert may exist for the same tenant, facility, location, alert type, and subject identity.
- Alert recalculation updates the existing active alert rather than duplicating it.
- Acknowledgement records the user, timestamp, and a mandatory note.
- Acknowledgement does not alter stock or resolve the underlying condition.
- The system resolves an alert only after its condition clears.
- When a resolved condition later recurs, create a new alert linked to the previous resolved alert.
- Alert history and acknowledgement records are immutable.
- Repeated recalculation must be idempotent.

Subject identity must be explicit and stable, for example medicine/location for reorder alerts and medicine/batch/location for expiry or batch-level variance alerts.

## 13. Alert configuration

Configuration supports:

- Reorder level
- Expiry horizon
- High-value monetary threshold by currency
- Quantity-percentage threshold
- Repeated-event count
- Lookback period

Configuration precedence:

```text
location override → facility default → tenant default
```

Configuration mutations require:

- `Idempotency-Key`
- Optimistic version
- Audit record
- Transactional rollback
- `409 Conflict` for stale versions or idempotency key/payload mismatch

Maker-checker is not required for P34 configuration. Changes do not rewrite historical alerts; the next alert recalculation uses the new effective configuration.

## 14. Permissions and default role mapping

Permissions:

```text
PHARMACY_DASHBOARD_VIEW
PHARMACY_REPORT_VIEW
PHARMACY_REPORT_EXPORT
PHARMACY_ALERT_VIEW
PHARMACY_ALERT_ACKNOWLEDGE
PHARMACY_ALERT_CONFIGURE
PHARMACY_AUDIT_VIEW
```

| Role | Dashboard | Reports | Export | Alert view | Acknowledge | Configure | Audit |
|---|---:|---:|---:|---:|---:|---:|---:|
| Pharmacist | Yes | Operational only | No | Yes | Yes | No | No |
| Pharmacy Manager | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Tenant Admin | Yes | Yes | Yes | Yes | No | Yes | Yes |
| Auditor | Yes | Yes | Yes | Yes | No | No | Yes |

“Operational only” excludes financial totals, inventory valuation, and audit data unless the pharmacist receives the corresponding additional permission.

Do not introduce broad `PHARMACY_ADMIN` or generic `REPORT_EXPORT` permissions. Backend enforcement is mandatory; frontend visibility is not authorization.

## 15. Audit authority

The existing transactional `audit_logs` mechanism is the authoritative audit source.

- Do not create `pharmacy_audit_trail` or a competing P34 audit store.
- Extend existing audit event types and structured metadata where required.
- Individual dashboard/report reads do not require audit events.
- Successful exports, alert acknowledgements, and configuration mutations must be audited.
- Failed exports must not create a successful-export audit event; failure logging may use the established operational logging mechanism.
- Audit reports read existing audit data under normal isolation and permission rules.
- Audit records remain append-only.

## 16. Cryptographic compliance

Cryptographic signing and hash chaining are excluded from P34.

Do not add:

- Signing keys
- Hash-chain columns
- Canonical cryptographic serialization
- Key rotation
- Cryptographically signed exports

Existing immutable transactional audit records and export metadata satisfy the P34 contract. Cryptographic compliance requires a separately approved future specification.

## 17. Report execution and pagination

P34 reports are synchronous and paginated.

Defaults and limits:

```text
default page size: 50
maximum page size: 200
maximum date range: 366 days
```

Rules:

- Apply stable deterministic sorting.
- Return total count and page metadata using established repository conventions.
- Validate authorization on every request.
- Do not introduce report-cache or asynchronous job tables.
- Reject invalid or excessive ranges using the established validation response.

## 18. CSV exports

P34 supports CSV export only.

- Maximum export size: 10,000 rows.
- Requests exceeding the limit must return a validation response requiring narrower filters.
- Authorization must be revalidated when export execution begins.
- CSV metadata must include tenant, facility, optional location filters, resolved timezone, currency, generated timestamp, generating user, report name, and report parameters.
- Exports are read-only and do not require maker-checker or idempotency keys.
- Every successful export creates exactly one audit event.
- A failed export must not create a successful-export audit event.
- Formula-injection-prone cell values beginning with `=`, `+`, `-`, or `@` must be safely escaped.
- Export content must match the same filters and formulas as the corresponding on-screen report.

## 19. Mutation guarantees

Alert acknowledgement and configuration mutations require:

- Mandatory `Idempotency-Key`
- Identical replay returns the original status and response
- Same key with a different payload returns `409 Conflict`
- Concurrent duplicate requests cause exactly one mutation
- Failed transactions do not retain successful idempotency records
- Append-only audit
- Complete rollback of status/configuration, acknowledgement, audit, and idempotency effects

Configuration updates additionally require optimistic versioning. Alert acknowledgement must validate the current active status and may replay an earlier successful acknowledgement only through its matching idempotency record.

Maker-checker is not required for acknowledgements, configuration, report reads, or exports.

## 20. Required API capabilities

Exact route names must follow existing Pharmacy conventions, but P34 must expose capabilities for:

- Read dashboard cards
- List and read alerts
- Acknowledge an alert
- Read effective alert configuration
- Create/update scoped alert configuration
- Run every required paginated report
- Export every exportable report as CSV
- Read Pharmacy audit events with filters

The service layer must own formulas, authorization, isolation, and transactional mutations; route handlers must not duplicate business calculations.

## 21. Frontend requirements

Provide:

- A new, separately routed, role-protected Pharmacy dashboard
- Card-to-report navigation with preserved filters
- Date, location, alert, status, medicine, batch, supplier, and other report-specific filters
- Paginated report tables
- Currency-separated financial display
- Inventory valuation with unvalued quantities clearly identified
- Alert list, classification, history, acknowledgement note, and effective configuration UI
- CSV export controls shown only with export permission
- Loading, empty, validation, forbidden, conflict, success, and server-error states
- Refresh/reload consistency
- Accessible labels, keyboard operation, and meaningful status text
- Duplicate-submit protection for mutations

The frontend must not calculate authoritative totals, alert classifications, or permissions independently of the backend.

The Pharmacy dashboard must use its own page/component boundary and data client. Existing general-dashboard components may be shared only when they are generic and their existing behaviour is preserved.

## 22. Data integrity, concurrency, and rollback

The implementation must provide:

- Tenant/facility/location isolation on every query and mutation
- Decimal-safe calculations
- Stable pagination and sorting
- Database constraints for active-alert deduplication and configuration scope
- Row locking or equivalent concurrency control for acknowledgement and configuration mutations
- Optimistic configuration versions
- Append-only audit records
- No duplicate active alerts, acknowledgements, configuration changes, or export-success audits
- Complete rollback on any failed mutation
- No mutation of accepted P30–P33 transactional records

## 23. Required acceptance coverage

P34 acceptance must verify:

1. Every required dashboard card and formula.
2. Tenant-local/facility-local business-date boundaries.
3. Currency separation and Decimal precision.
4. Gross, discount, tax, invoice-net, refund, and net-paid definitions.
5. Every required report and filter.
6. Pagination, stable ordering, date-range limits, and export limits.
7. Current-stock and valuation formulas, including unvalued stock.
8. Fast-, slow-, and non-moving boundaries and ties.
9. Every alert type and exact threshold boundary.
10. Expired and 0–30/31–60/61–90-day buckets.
11. Alert deduplication, update, acknowledgement, resolution, and recurrence.
12. Configuration precedence and optimistic conflicts.
13. RBAC for allowed and denied roles.
14. Cross-tenant, cross-facility, and unauthorized-location isolation.
15. Idempotency replay and payload mismatch.
16. Concurrent duplicate acknowledgement/configuration actions.
17. Rollback proving no partial mutation, audit, or idempotency effect.
18. Successful and failed CSV export auditing.
19. CSV formula-injection protection.
20. Existing audit-log authority with no competing Pharmacy audit table.
21. Migration `0087 → 0088 → 0087 → 0088` across all configured schemas.
22. Focused P34 and real PostgreSQL acceptance suites.
23. Pharmacy and full-backend regression.
24. Frontend type-check, ESLint, complete unit suite, and production build.
25. Deterministic P34 E2E seed/reset.
26. Chromium primary success, permission-denial, alert mutation, and export paths.
27. General-dashboard regression proving its route, cards, permissions, and loading behaviour remain unchanged.

Tests must not use expiring fixed dates, weaken assertions, bypass backend controls, or count skipped/did-not-run browser tests as acceptance.

## 24. Acceptance decision

Recommend **P34 ACCEPT** only when:

- This complete contract is implemented.
- Migration `0088` is validated across every configured schema and is the sole final head.
- Focused and real PostgreSQL P34 acceptance tests pass.
- Pharmacy and full backend regressions pass with exit code `0`.
- Frontend type-check, ESLint, complete unit suite, and production build pass.
- All required Chromium tests execute and pass with no skipped or did-not-run cases.
- RBAC, isolation, formulas, alerts, audit, idempotency, concurrency, CSV safety, and rollback are verified.
- No critical or high P34 defect remains.

Otherwise recommend **P34 NOT ACCEPTED**, report the blockers, and do not begin Lab or another phase.

## 25. Implementation controls

- Confirm `0087` remains the sole repository and database head before creating `0088`.
- Confirm `0088` remains unused.
- Correct conflicting preliminary P34 models and mock assertions; P34 has not been accepted or released.
- Use `P34_DASHBOARD_REPORTS_VERIFICATION.md` only for implementation evidence, commands, exact results, defects, and recommendation.
- Update `P30_P34_MASTER_PLAN.md` to link to this specification.
- Mark the master plan complete only after every mandatory gate passes.
- Preserve unrelated staged, unstaged, and untracked changes.
- Do not commit, merge, push, deploy, rebase, reset, stash, clean, start Lab, or begin another phase.
- Stop after the complete P34 acceptance report and wait for explicit approval.
