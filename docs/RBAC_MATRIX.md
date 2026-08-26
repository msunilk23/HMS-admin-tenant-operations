# RBAC Matrix

Backend dependencies are authoritative. Frontend route and navigation guards are UX only.

| Capability | Receptionist | Nurse | Doctor | Pharmacist | Lab technician | Billing officer | Hospital admin | Super admin |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Patient search/register | Yes | No | Yes | No | No | No | Yes | Platform only |
| Register visit / queue token | Yes | No | No | No | No | No | Yes | No tenant access |
| Nurse queue / pre-vitals | No | Yes | No | No | No | No | Yes | No tenant access |
| Doctor queue / consultation | No | No | Yes | No | No | No | Yes | No tenant access |
| Prescription | No | No | Yes | Read for dispensing | No | No | Yes | No tenant access |
| Lab order/result workflow | Read | Read | Create/read | No | Operate | No | Yes | No tenant access |
| Pharmacy dispensing | Read | Read | No | Operate | No | No | Yes | No tenant access |
| Billing/payment | Read | Limited payment admission | No | Pharmacy billing context | No | Operate | Yes | Platform configuration only |
| Feedback read/submit | Submit/read | Submit/read | Submit/read | No | No | No | Manage | No tenant access |
| Nurse roster | No | Read own | No | No | No | No | Manage | No tenant access |
| Tenant features/plan | No | No | No | No | No | No | No | Manage platform-wide |
| User/role management | No | No | No | No | No | No | Manage tenant staff | Manage platform users/tenants |
| Audit records | No direct access | No direct access | No direct access | No direct access | No direct access | No direct access | Tenant administration scope | Platform scope |

## Enforcement rules

- Every tenant route is protected by tenant context and role dependencies.
- `super_admin` uses `/api/v1/super/*` and is blocked from tenant-scoped routes.
- Doctors are filtered to their assigned doctor and department.
- Nurses are filtered to assigned departments and roster scope.
- Feature dependencies are evaluated from tenant entitlements; missing or invalid tenant context is rejected.
- The client cannot submit role, tenant, workflow status, payment state, or audit identity as an authorization override.

---

## Pharmacy Extended Permissions

The current Pharmacist/Hospital Admin capabilities remain valid. The expanded Pharmacy module introduces granular permissions using the existing authorization framework rather than frontend role-name checks.

Initial P25 permissions should be equivalent to:

- `PHARMACY_MASTER_VIEW`
- `PHARMACY_MASTER_CREATE`
- `PHARMACY_MASTER_EDIT`
- `PHARMACY_FORMULARY_MANAGE`

Future permissions should distinguish:

- pharmacy dispensing
- pharmacy manager approval
- supplier/procurement management
- GRN receiving
- inventory viewing
- stock adjustment
- stock transfer
- physical count
- variance approval
- reports/audit

Future operational roles may include `PHARMACIST`, `PHARMACY_MANAGER`, and `STORE_MANAGER`, but roles/permissions must reuse the repository's existing RBAC model and require task-level approval before schema changes.

Platform Super Admin does not automatically receive tenant clinical/pharmacy mutation rights.
