# SaaS Feature Entitlements System — Implementation Plan

> **Goal:** `super_admin` controls which features each tenant hospital can access.
> Features are enforced at the API level (backend), JWT level (propagation), and UI level (frontend guards).
> This makes the product fully SaaS-ready with plan-based feature gating and per-tenant overrides.

---

## Feature Registry

Every module maps to a feature key. These keys are the single source of truth across DB, JWT, and UI.

| Feature Key | Module | Roles that use it |
|---|---|---|
| `opd_queue` | OPD Queue Dashboard, Token Board | receptionist, nurse |
| `appointments` | Appointment Booking & Calendar | receptionist, doctor |
| `vitals` | Nurse Vitals Capture | nurse |
| `nurse_roster` | Nurse Duty Roster & Room Assignment | nurse |
| `lab` | Lab Orders, Result Entry, PDF Upload | doctor, lab_technician |
| `pharmacy` | Pharmacy Dispensing Queue | pharmacist, doctor |
| `billing` | Invoice Generation, Payments | billing_officer |
| `razorpay` | Online Payment via POS Kiosk | billing_officer, receptionist |
| `whatsapp_sms` | Twilio SMS/WhatsApp Notifications | system (auto-triggered) |
| `cloudinary_reports` | Lab PDF Upload to Cloud | lab_technician |

> Adding a new feature in future = add a row here + one `require_feature()` call on the router. No other code changes needed.

---

## Subscription Plans (Tier Defaults)

Plans define the **default feature set** assigned when a new tenant is created.
`super_admin` can override individual features per tenant after creation.

| Plan | Included Features |
|---|---|
| `starter` | `opd_queue`, `vitals`, `appointments` |
| `standard` | + `lab`, `pharmacy`, `billing` |
| `enterprise` | + `razorpay`, `whatsapp_sms`, `cloudinary_reports`, `nurse_roster` |

> Existing tenants (pre-entitlements) are seeded with **all features enabled** — fully backward compatible, nothing breaks.

---

## Data Model Changes

### New table: `public.tenant_features`

```sql
CREATE TABLE public.tenant_features (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    feature     TEXT NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT true,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, feature)
);
```

### Changes to `public.tenants`

```sql
ALTER TABLE public.tenants
    ADD COLUMN plan TEXT NOT NULL DEFAULT 'enterprise';
    -- starter | standard | enterprise
    -- is_active already exists — enforce on every login (currently not enforced)
```

### New SQLAlchemy model

**File:** `backend/app/models/public/tenant_feature.py`

```python
class TenantFeature(Base, TimestampMixin):
    __tablename__ = "tenant_features"
    __table_args__ = {"schema": "public"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("public.tenants.id"), nullable=False)
    feature: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
```

---

## Backend Architecture

### Phase B — Feature Injection into JWT

**File:** `backend/app/api/v1/auth.py` → `login` endpoint

After user authentication, query `tenant_features` for the tenant and embed `features: list[str]` in the access token:

```python
# New JWT payload
{
  "sub": "user-uuid",
  "role": "hospital_admin",
  "tenant_schema": "shankar",
  "hospital_name": "Shankar Super Speciality",
  "features": ["opd_queue", "lab", "pharmacy", "billing", "appointments"]
}
```

Old tokens without `features` claim → treated as full-access during transition window.

### Phase C — `require_feature()` Dependency

**File:** `backend/app/core/dependencies.py`

```python
def require_feature(feature: str):
    """Enforces that the authenticated tenant has the feature enabled."""
    async def _check(current_user: dict = Depends(get_current_user)) -> dict:
        features = current_user.get("features") or []
        if feature not in features:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Feature '{feature}' is not enabled for your plan."
            )
        return current_user
    return _check
```

**Apply to routers:**

| Router file | Feature key to add |
|---|---|
| `lab.py` | `require_feature("lab")` |
| `pharmacy.py` | `require_feature("pharmacy")` |
| `billing.py` | `require_feature("billing")` |
| `appointments.py` | `require_feature("appointments")` |
| `queue.py` | `require_feature("opd_queue")` |
| `vitals.py` | `require_feature("vitals")` |
| `nurse_departments.py` | `require_feature("nurse_roster")` |

### Phase D — Tenant Suspend Enforcement

**File:** `backend/app/api/v1/auth.py` → `login`

After user lookup, check `tenant.is_active`. If `False`:

```python
raise HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="This hospital account has been suspended. Please contact support."
)
```

> Currently `is_active` exists on the `Tenant` model but is **never checked on login** — this is a security gap.

### Phase E — Super Admin Tenant Management API

**New file:** `backend/app/api/v1/super_admin.py`  
**Router prefix:** `/super`  
**All endpoints:** `require_role("super_admin")`

| Method | Path | Description |
|---|---|---|
| `GET` | `/super/tenants` | List all tenants with plan, status, feature summary |
| `GET` | `/super/tenants/{tenant_id}` | Single tenant detail + all feature toggles |
| `PATCH` | `/super/tenants/{tenant_id}` | Update plan or is_active |
| `PUT` | `/super/tenants/{tenant_id}/features` | Bulk-set all features (e.g. on plan change) |
| `PATCH` | `/super/tenants/{tenant_id}/features/{feature}` | Toggle a single feature on/off |
| `GET` | `/super/features` | Returns canonical list of all known feature keys |

---

## Frontend Architecture

### Tenant administrator password recovery

From the tenant detail panel, an active Super Admin can reset the single active
tenant `hospital_admin`. The action requires a reason and terminates the
administrator's existing sessions. The generated temporary password is shown
once in memory with a copy action; closing the panel clears it. The
administrator must change it immediately after login.

The API is `POST /api/v1/super/tenants/{tenant_id}/admin/reset-password`.
It rejects inactive tenants, missing or ambiguous administrators, all other
roles, and repeated requests over the Redis-backed limit. PostgreSQL user
session versioning and `tokens_valid_after` remain authoritative if Redis is
unavailable. Platform audit records contain actor, tenant, target, reason,
request ID, and source IP, but never a password, hash, JWT, or Redis value.

### Phase F — authStore: expose features

**File:** `frontend/src/features/auth/authStore.ts`

- Parse `features: string[]` from JWT payload in `setTokens()`
- Add to state: `features: string[]`
- Add helper: `hasFeature(key: string): boolean`

```typescript
// In AuthState interface
features: string[]
hasFeature: (key: string) => boolean

// In setTokens()
features: (payload.features as string[]) ?? [],

// hasFeature helper
hasFeature: (key: string) => get().features.includes(key),
```

### Phase G — Sidebar Nav Guard

**File:** `frontend/src/components/shared/Layout.tsx`

- Add optional `feature?: string` to `NavItem` interface
- Filter: hide item if `item.feature && !hasFeature(item.feature)`

| Nav Item | Feature key |
|---|---|
| OPD Queue | `opd_queue` |
| Appointments | `appointments` |
| Vitals | `vitals` |
| Nurse Roster | `nurse_roster` |
| Lab | `lab` |
| Pharmacy | `pharmacy` |
| Billing | `billing` |

### Phase H — Route Feature Guard

**New component:** `frontend/src/components/shared/FeatureGuard.tsx`

```typescript
// If the tenant doesn't have the feature, redirect to /dashboard
export default function FeatureGuard({ feature, children }) {
  const hasFeature = useAuthStore(s => s.hasFeature)
  if (!hasFeature(feature)) return <Navigate to="/dashboard" replace />
  return children
}
```

Wrap feature-sensitive routes in `App.tsx`:

```tsx
<Route path="/lab" element={
  <FeatureGuard feature="lab">
    <RoleGuard allowed={LAB}><LabPage /></RoleGuard>
  </FeatureGuard>
} />
```

### Phase I — Super Admin Tenant Management UI

**New file:** `frontend/src/features/super_admin/TenantsPage.tsx`  
**Route:** `/super/tenants`  
**Sidebar:** "Tenants" nav item visible only to `super_admin`

**UI Components:**
- Tenants table: hospital name, plan badge, active/suspended status, feature count
- Click row → detail drawer/panel:
  - Plan selector (dropdown: Starter / Standard / Enterprise) → auto-updates feature toggles via `PUT /super/tenants/{id}/features`
  - Feature grid: toggle switch per feature with label, instant `PATCH` on toggle
  - Suspend / Reactivate button with confirmation dialog
- Toast notifications on every change

---

## Implementation Phases

### ✅ Pre-work (Already Done)
- `super_admin` excluded from hospital staff list (`users.py` query filter)
- `hospital_admin` has Dashboard nav item + landing page
- Session expired modal on secret key rotation

---

### Phase 1 — Foundation *(No UI changes, 100% backward compatible)*

- [ ] Alembic migration `0012_tenant_features.py`:
  - Add `plan TEXT NOT NULL DEFAULT 'enterprise'` to `public.tenants`
  - Create `public.tenant_features` table
  - Seed all existing tenants with all 10 features `enabled=true`
- [ ] `TenantFeature` SQLAlchemy model in `backend/app/models/public/tenant_feature.py`
- [ ] Register model in `backend/app/models/public/__init__.py`
- [ ] `require_feature()` dependency added to `dependencies.py` (no router uses it yet)

**Checkpoint:** Run `docker-compose up` — system works identically to before. DB has new table.

---

### Phase 2 — JWT Propagation *(No enforcement yet)*

- [ ] `auth.py` login: query `tenant_features` WHERE `tenant_id = tenant.id AND enabled = true`
- [ ] Embed `features: list[str]` in access token extra claims
- [ ] `authStore.ts`: parse `features[]` from JWT payload, expose `hasFeature(key)`
- [ ] Persist `features` in Zustand store (partialize)

**Checkpoint:** Login → open DevTools → decode JWT → see `features` array. No UI changes yet.

---

### Phase 3 — Backend Enforcement *(Gate opens here)*

- [ ] Apply `require_feature()` to all 7 routers listed above
- [ ] `auth.py` login: check `tenant.is_active` before issuing tokens
- [ ] Restart backend → test: call `/lab` endpoint without `lab` in features → expect `403`

**Checkpoint:** Disabling `lab` for a tenant via DB → lab tech gets 403 on all lab endpoints.

---

### Phase 4 — Frontend UI Guards *(UX layer)*

- [ ] `Layout.tsx`: add `feature?` to `NavItem`, filter in `visibleItems`
- [ ] `FeatureGuard.tsx`: new component redirecting on missing feature
- [ ] `App.tsx`: wrap feature routes with `FeatureGuard`

**Checkpoint:** Tenant without `pharmacy` → pharmacist sees no Pharmacy in sidebar, direct URL redirects to dashboard.

---

### Phase 5 — Super Admin Tenant Management *(New functionality)*

- [ ] `super_admin.py` backend router with all 6 endpoints
- [ ] Register `super_admin_router` in `router.py` with prefix `/super`
- [ ] `TenantsPage.tsx` frontend with table + detail panel + toggles + plan selector
- [ ] `FeatureGuard` wrapping `/super/tenants` route for `super_admin` only
- [ ] Sidebar: "Tenants" nav item for `super_admin` role
- [ ] `App.tsx`: add `/super/tenants` route

**Checkpoint:** `super_admin` logs in → sees Tenants page → can toggle features per hospital → hospital's JWT on next login reflects changes.

---

### Phase 6 — Hardening & Production Readiness

- [ ] Refresh token blocklist in Redis — store `jti` claim; on logout/suspend, add to blocklist; check on every refresh
- [ ] Nginx per-tenant rate limiting (`limit_req_zone $http_tenant_schema`)
- [ ] `public.audit_log` table wired to existing `audit.py` middleware (currently writes where?)
- [ ] Password reset via time-limited token link (replace SMS plaintext temp password — security risk)
- [ ] Usage metering: `public.tenant_usage` table tracking visit count / API calls per tenant per month

**Checkpoint:** Suspend tenant → existing refresh tokens are rejected → all users forced to login → 403 on login.

---

## Open SaaS Concerns (Future Roadmap)

| Concern | Priority | Notes |
|---|---|---|
| Self-service tenant onboarding | High | Hospital signs up → tenant auto-provisioned → email verification flow |
| Stripe billing integration | High | Tie plan tier to Stripe subscription; auto-downgrade on payment failure |
| Subdomain routing per tenant | Medium | `shankar.yourdomain.com` via nginx wildcard cert — better than schema-based URL |
| DPDP / HIPAA audit trail | High | India DPDP Act mandates patient data access logs; audit_log must be complete |
| Tenant data export | Medium | Hospital admin can export all their data (GDPR-equivalent right) |
| Tenant data deletion | Medium | Safe `DROP SCHEMA CASCADE` flow with confirmation + backup |
| Usage-based billing | Medium | Charge per visit/consultation above plan threshold |
| Multi-region tenants | Low | Route tenants to nearest DB region for latency |

---

## Files Touched Per Phase

| Phase | Backend files | Frontend files |
|---|---|---|
| 1 | `alembic/versions/0012_tenant_features.py`, `models/public/tenant_feature.py`, `models/public/__init__.py`, `core/dependencies.py` | — |
| 2 | `api/v1/auth.py` | `features/auth/authStore.ts` |
| 3 | `api/v1/lab.py`, `pharmacy.py`, `billing.py`, `appointments.py`, `queue.py`, `vitals.py`, `nurse_departments.py`, `auth.py` | — |
| 4 | — | `components/shared/Layout.tsx`, `components/shared/FeatureGuard.tsx`, `App.tsx` |
| 5 | `api/v1/super_admin.py`, `api/v1/router.py` | `features/super_admin/TenantsPage.tsx`, `components/shared/Layout.tsx`, `App.tsx` |
| 6 | `core/security.py`, `api/v1/auth.py`, `middleware/audit.py`, `alembic/versions/0013_audit_log.py` | `features/auth/LoginPage.tsx` (password reset link) |
