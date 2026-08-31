# P30 Implementation: Patient Return + Supplier Return

**Status**: Core implementation complete, migrations pending verification

## Overview

P30 adds comprehensive patient and supplier return management to the pharmacy module, enabling:
- Patient returns with restockability assessment
- Supplier returns with approval workflow
- Stock ledger integration for returns
- Refund processing coordination with billing module
- Full audit trail and tenant/facility isolation

## Architecture

### Database Models

#### Patient Returns
- **PatientReturn**: Header record tracking return lifecycle
  - Status flow: REQUESTED → VALIDATED → ACCEPTED → REFUND_PENDING → REFUNDED → RESTOCKED
  - Alternative rejection path: REQUESTED → VALIDATED → REJECTED
  - Tracks restockable vs non-restockable item counts
  - Links to original dispense, invoice, patient, visit

- **PatientReturnItem**: Line items within a return
  - Links to specific pharmacy_dispense_item
  - Tracks returned quantity and unit price
  - Stores restockability assessment and reason
  - Creates stock ledger transaction on acceptance

#### Supplier Returns
- **SupplierReturn**: Header record for supplier return workflow
  - Status flow: REQUESTED → APPROVED → DISPATCHED → RECEIVED
  - Links to supplier, GRN (goods_receipt), pharmacy_location
  - Tracks total return quantity and value

- **SupplierReturnItem**: Individual batches being returned
  - Links to specific inventory_batch
  - Tracks received vs returned quantity
  - Creates stock ledger transaction on dispatch

### API Endpoints

#### Patient Returns
```
POST /api/v1/returns/patient-returns
  - Request patient return for dispensed medicines
  - Requires: PHARMACY_RETURN_REQUEST
  - Validates dispense exists and items available

POST /api/v1/returns/patient-returns/{return_id}/validate
  - Validate items for restockability
  - Requires: PHARMACY_RETURN_VALIDATE
  - Marks items ACCEPTED/REJECTED based on condition

POST /api/v1/returns/patient-returns/{return_id}/accept
  - Accept validated return and restock items
  - Requires: PHARMACY_RETURN_ACCEPT
  - Creates PATIENT_RETURN_RESTOCK ledger transactions
  - Marks return REFUND_PENDING

POST /api/v1/returns/patient-returns/{return_id}/reject
  - Reject return (before or after validation)
  - Requires: PHARMACY_RETURN_REJECT
  - Sets rejection reason

GET /api/v1/returns/patient-returns/{return_id}
  - Retrieve return details with items
```

#### Supplier Returns
```
POST /api/v1/returns/supplier-returns
  - Request supplier return
  - Requires: SUPPLIER_RETURN_REQUEST
  - Validates batches exist and quantities available

POST /api/v1/returns/supplier-returns/{return_id}/approve
  - Approve return request
  - Requires: SUPPLIER_RETURN_APPROVE

POST /api/v1/returns/supplier-returns/{return_id}/dispatch
  - Dispatch return (reduces stock)
  - Requires: SUPPLIER_RETURN_DISPATCH
  - Creates SUPPLIER_RETURN ledger transactions with negative quantity

POST /api/v1/returns/supplier-returns/{return_id}/receive
  - Confirm return received from supplier
  - Requires: SUPPLIER_RETURN_RECEIVE

GET /api/v1/returns/supplier-returns/{return_id}
  - Retrieve return details with items
```

### Services

#### PatientReturnService
Core business logic methods:

- `request_return()`: Create return request
  - Validates dispense exists and belongs to patient
  - Validates all items reference existing dispense_items
  - Prevents duplicate active returns on same dispense
  - Generates unique reference_key
  - Creates patient_return and patient_return_items records

- `validate_return()`: Assess restockability
  - Validates return in REQUESTED status
  - Marks each item ACCEPTED if restockable, else REJECTED
  - Updates parent return with item counts
  - Transitions return to VALIDATED

- `accept_return()`: Finalize restocking
  - Creates stock ledger PATIENT_RETURN_RESTOCK transactions
  - Records restock_ledger_transaction_id on each item
  - Transitions return to REFUND_PENDING
  - Triggers billing service for refund processing

- `reject_return()`: Decline return
  - Records rejection reason
  - Transitions to REJECTED state

- `mark_refunded()`: Called by billing service
  - Records refund amount and timestamp
  - Transitions to REFUNDED state

#### SupplierReturnService
Core business logic methods:

- `request_return()`: Create return request
  - Validates supplier exists
  - Validates batches exist in location
  - Prevents over-return (returned_qty ≤ available_qty)
  - Generates unique reference_key
  - Creates supplier_return and supplier_return_items records

- `approve_return()`: Approve request
  - Transitions from REQUESTED to APPROVED

- `dispatch_return()`: Reduce stock and dispatch
  - Creates stock ledger SUPPLIER_RETURN transactions
  - Uses negative quantity to represent stock reduction
  - Records stock_reduction_ledger_id on each item
  - Transitions to DISPATCHED

- `receive_return()`: Confirm receipt
  - Transitions from DISPATCHED to RECEIVED

## Key Features

### 1. Stock Ledger Integration
- Patient returns create PATIENT_RETURN_RESTOCK entries with positive quantity
- Supplier returns create SUPPLIER_RETURN entries with negative quantity
- All transactions are append-only (never deleted)
- Enables stock reconciliation: `sum(ledger.quantity) = current_stock`

### 2. Restockability Assessment
- Patient return items independently marked as restockable/non-restockable
- Non-restockable items tracked with reason (damaged, opened, expired, etc.)
- Restockable items immediately returned to inventory
- Non-restockable items removed from stock via write-off ledger (P31)

### 3. Refund Processing
- Patient returns coordinate with billing module for refunds
- Refund amount calculated from line_items prices
- Idempotent refund processing (Refund model with unique constraints)
- Payment retry handled by existing billing infrastructure

### 4. Idempotency Guarantees
- Unique constraints prevent duplicate return requests
- Existence checks before state transitions
- DB-backed uniqueness (not just business logic)
- Safe retry behavior on network failures

### 5. Audit Trail
- All state transitions recorded via audit_service
- Captures user_id, timestamp, old_value, new_value for each action
- Immutable audit logs (no updates, only inserts)
- Enables compliance and investigation

### 6. Tenant/Facility Isolation
- All queries scoped to tenant_id via session search_path
- facility_id FK ensures facility-level scoping
- pharmacy_location_id for multi-location pharmacy operations
- No cross-tenant or cross-facility data leakage

## Migration

### 0080_p30_patient_supplier_returns.py
Creates four tables with idempotent logic:

1. **patient_returns** (48 columns)
   - UUID PK, tenant/facility/location FKs
   - Status enum with CHECK constraint
   - Audit timestamps (requested_at, validated_at, accepted_at, refunded_at)
   - Indexes on: tenant_id, facility_id, patient_id, status, reference_key

2. **patient_return_items** (18 columns)
   - UUID PK, FK to patient_returns (CASCADE on delete)
   - FK to pharmacy_dispense_items, medicine_products, inventory_batches
   - Status enum (PENDING_VALIDATION, ACCEPTED, REJECTED)
   - Restockability flag with reason
   - Indexes on: return_id, dispense_item_id

3. **supplier_returns** (23 columns)
   - UUID PK, tenant/facility/location/supplier FKs
   - Optional FKs to purchase_orders, goods_receipts
   - Status enum with CHECK constraint
   - Audit timestamps for approval/dispatch/receive workflow
   - Indexes on: tenant_id, facility_id, supplier_id, status

4. **supplier_return_items** (11 columns)
   - UUID PK, FK to supplier_returns (CASCADE on delete)
   - FK to inventory_batches, stock_transactions
   - Indexes on: supplier_return_id, inventory_batch_id

All tables include `created_at`/`updated_at` timestamp columns (server default).

## Implementation Status

### Completed ✅
1. **Models** (returns.py)
   - PatientReturn, PatientReturnItem
   - SupplierReturn, SupplierReturnItem
   - All relationships and constraints defined

2. **Schemas** (schemas/returns.py)
   - Create/Read schemas with nested items
   - Validation rules via Pydantic
   - Type-safe request/response contracts

3. **Services** (services/returns_service.py)
   - Complete business logic for both return types
   - Stock ledger integration
   - Idempotency checks
   - Audit trail recording

4. **API Endpoints** (api/v1/returns.py)
   - All endpoints defined with RBAC guards
   - Proper error handling and HTTP status codes
   - Dependency injection for session/user/tenant
   - Route integration in main router

5. **Tests** (tests/test_p30_returns.py)
   - Unit tests for all service methods
   - Integration tests for workflows
   - Idempotency validation
   - Mock-based (no DB dependency)

6. **Migration** (alembic/versions/0080_p30_*.py)
   - Idempotent table creation
   - Comprehensive indexes
   - Constraint definitions

### In Progress 🔄
- Migration application (0077-0080 sequence)
- Database connection/schema validation

### TODO ⚠️
- Concurrency tests (multi-user simultaneous returns)
- Ledger reconciliation tests
- E2E Playwright workflows
- Integration with P31 (expiry/damage handling)
- Return history/reporting
- Partial return scenarios (return subset of items)
- Return cancellation workflow (cancel after ACCEPTED)

## Known Issues & Limitations

### Migration
- Migrations 0077-0079 may encounter duplicate index errors
- Fixed with idempotent `has_table()` and `has_index()` checks
- Recommend downgrade to 0075 + fresh upgrade if issues persist

### Outstanding Implementation
- Return amounts calculated from invoice line items (currently placeholder)
- Refund integration with billing requires coordination
- Batch-level restockability assessment (currently item-level only)
- Return reason categorization (currently free text)

### Performance Considerations
- No pagination on return lists (TODO: add limit/offset)
- No search/filter on return reason text
- Stock ledger query not optimized for large histories
- Recommend indexes on (tenant_id, facility_id, reference_type) for ledger

## Testing Strategy

### Unit Tests (test_p30_returns.py)
- Mock-based, no DB
- Tests all service methods
- Validates state transitions
- Checks idempotency

### Integration Tests (TODO)
- Real database
- Full return workflows
- Stock ledger verification
- Refund processing coordination

### E2E Tests (TODO)
- Playwright scenarios
- User workflows
- Multi-step approval processes
- Error recovery

### Concurrency Tests (TODO)
- Simultaneous returns on same dispense
- Concurrent stock updates
- Race condition detection

## API Usage Examples

### Patient Return Flow
```bash
# 1. Request return
POST /api/v1/returns/patient-returns
{
  "dispense_id": "...",
  "return_reason": "Medicine expired",
  "package_condition": "Sealed",
  "items": [
    {
      "dispense_item_id": "...",
      "returned_quantity": 5,
      "restockable": true
    }
  ]
}

# 2. Validate restockability
POST /api/v1/returns/patient-returns/{return_id}/validate

# 3. Accept and restock
POST /api/v1/returns/patient-returns/{return_id}/accept

# 4. Billing service marks refunded (internal)
# Refund created, invoice adjusted, refund_amount set
```

### Supplier Return Flow
```bash
# 1. Request return
POST /api/v1/returns/supplier-returns
{
  "supplier_id": "...",
  "goods_receipt_id": "...",
  "return_reason": "Damaged batch",
  "items": [
    {
      "inventory_batch_id": "...",
      "returned_quantity": 20,
      "unit_cost": 50.00
    }
  ]
}

# 2. Approve
POST /api/v1/returns/supplier-returns/{return_id}/approve

# 3. Dispatch (reduces stock)
POST /api/v1/returns/supplier-returns/{return_id}/dispatch

# 4. Receive confirmation
POST /api/v1/returns/supplier-returns/{return_id}/receive
```

## Dependencies

### Required
- PostgreSQL 16.15
- SQLAlchemy 2.x async
- Pydantic v2
- FastAPI

### Integration Points
- **Billing Module**: Refund creation via Refund model
- **Stock Ledger**: PATIENT_RETURN_RESTOCK, SUPPLIER_RETURN transactions
- **Audit Module**: record_audit() service
- **RBAC**: require_permission() decorator

## RBAC Permissions (To be added)

New permissions needed:
- PHARMACY_RETURN_REQUEST
- PHARMACY_RETURN_VALIDATE
- PHARMACY_RETURN_ACCEPT
- PHARMACY_RETURN_REJECT
- SUPPLIER_RETURN_REQUEST
- SUPPLIER_RETURN_APPROVE
- SUPPLIER_RETURN_DISPATCH
- SUPPLIER_RETURN_RECEIVE

Typical role assignments:
- **Pharmacist**: All patient return permissions
- **Store Manager**: All supplier return permissions
- **Pharmacy Manager**: All permissions

## Next Steps (P31-P34)

### P31: Expiry + Damage + Recall
- Add batch status flags (expired, damaged, quarantined, recalled)
- Implement quarantine logic (prevents dispensing)
- Recall traceability (link to prior dispenses)
- Disposal/write-off workflow

### P32: Stock Transfer
- Multi-location transfer workflow
- FEFO preservation across locations
- Partial receive support
- Location-level isolation

### P33: Cycle Count
- Physical inventory count sessions
- Variance calculation
- Approval workflow
- Stock adjustments via ledger

### P34: Dashboard + Reports
- Operational cards (low stock, expiring, expired, quarantined, recalled, pending)
- Alerts with threshold configuration
- Comprehensive reports (stock, dispensing, returns, transfers)
- Export to CSV/Excel/PDF
- Audit view with immutable events

## Performance & Scale

### Expected Volumes
- Patient returns: ~5-10 per day per facility
- Supplier returns: ~10-20 per day per facility
- Ledger entries: ~100+ per day per location

### Query Performance
- Patient return lookup by dispense_id: O(log n) via index
- Supplier return lookup by supplier_id: O(log n) via index
- Ledger sum for stock: O(n) where n = number of transactions
  - Recommend materialized view for real-time stock
  - Or cache with invalidation on ledger write

### Recommendations
1. Paginate return lists (20-50 per page)
2. Materialize current stock view
3. Archive historical ledger (1+ year old)
4. Add search/filter capabilities
5. Consider read replicas for reporting queries

---

**Document Version**: 1.0  
**Last Updated**: Current Implementation  
**Status**: Ready for testing and P31-P34 implementation
