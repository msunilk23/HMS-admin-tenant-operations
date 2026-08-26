# HMS Architecture

## 1. Architecture Objective

Build a secure, modular, multi-tenant Hospital Management System capable of evolving from OPD into a complete Smart Hospital platform.

Current priority:

**OPD Core**

Future capabilities include:

* IP
* ER
* OT
* ICU
* Ward
* Pharmacy
* Lab
* Billing
* Finance
* Home Care
* Mobile applications
* AI
* RTLS
* Camera analytics

Current architecture must not prematurely implement these future modules but should avoid blocking them.

---

# 2. Logical Architecture

Users

↓

React Frontend

↓

FastAPI Backend

↓

Domain Services

↓

SQLAlchemy

↓

PostgreSQL

Supporting infrastructure:

FastAPI
↔ Redis
↔ WebSocket

External integrations may include:

* payment gateway
* SMS
* WhatsApp
* email
* future PACS/LIS/device systems

---

# 3. Multi-Tenant Architecture

Platform:

Super Admin

↓

Hospitals / Tenants

Each hospital has isolated operational/clinical data.

Tenant context is derived from authenticated server-trusted identity.

Client-supplied tenant identity must not override authenticated tenant context.

Platform APIs and tenant APIs remain logically separated.

---

# 4. Backend Layers

Recommended separation:

API Routes
↓
Authorization / Validation
↓
Domain Service
↓
Repository / ORM
↓
PostgreSQL

Business-critical workflow logic should not be duplicated across API routes.

Examples:

* VisitWorkflowService
* payment processing service
* tenant provisioning service

---

# 5. Frontend

React/TypeScript frontend should provide role-oriented workflows.

Frontend responsibilities:

* presentation
* navigation
* form validation
* UX
* API interaction
* WebSocket updates

Frontend must not be the sole enforcement location for:

* RBAC
* tenant isolation
* workflow transitions
* payment state
* clinical authorization

---

# 6. PostgreSQL

PostgreSQL is the authoritative persistent store.

Contains:

* users/platform metadata as designed
* patients
* appointments
* visits
* clinical data
* pharmacy data
* lab data
* billing
* audit
* configuration

Schema changes are managed using Alembic.

---

# 7. Redis

Redis is supporting infrastructure.

Use cases:

* feature caching
* refresh-token revocation
* Pub/Sub
* WebSocket coordination
* temporary locks/cache where appropriate

Redis is not the source of truth for clinical or financial transactions.

---

# 8. WebSocket Architecture

Business mutation:

API
→ PostgreSQL commit
→ publish event
→ Redis Pub/Sub
→ WebSocket clients

Clients receiving events should refresh authoritative data where required.

Events must be tenant isolated.

---

# 9. OPD Domain

Core relationship:

Patient
→ Appointment
→ Visit

Visit
├── QueueToken
├── Vitals
├── Consultation
├── Prescription
├── LabOrder
├── Invoice
└── Feedback

`visit_id` is the encounter backbone.

---

# 10. Domain Separation

Visit controls OPD clinical lifecycle.

Independent modules control their own lifecycle.

Do not create a single giant status field representing the entire hospital journey.

This principle applies to future modules as well.

---

# 11. Security Architecture

Security layers:

Authentication
→ Tenant Isolation
→ Feature Authorization
→ Role Authorization
→ Resource Authorization
→ Domain Validation
→ Audit

All layers are required where applicable.

---

# 12. Authentication

JWT identifies authenticated user and trusted tenant context.

Refresh tokens support revocation.

Temporary staff credentials require password change.

Secrets must not be logged.

---

# 13. RBAC

Roles should be enforced by backend APIs.

Typical roles:

* receptionist
* nurse
* doctor
* pharmacist
* lab
* billing
* hospital_admin
* super_admin

Future roles may be added without redesigning tenant architecture.

---

# 14. Feature Controls

Tenant subscription/configuration may enable/disable modules.

Feature evaluation:

PostgreSQL
→ optional Redis cache
→ backend authorization
→ frontend route/navigation

Backend remains authoritative.

---

# 15. Release Surfaces

The stabilized OPD release includes:

* visit-linked feedback
* nurse roster assignments and attendance
* semantic TAT timestamps and the visit TAT endpoint
* tenant-scoped RBAC and feature enforcement
* audit metadata and secret-safe snapshots
* Redis-backed tenant-isolated real-time events

See [API.md](API.md), [RBAC_MATRIX.md](RBAC_MATRIX.md), [TENANT_ARCHITECTURE.md](TENANT_ARCHITECTURE.md), [STATE_DIAGRAMS.md](STATE_DIAGRAMS.md), and [DEPLOYMENT.md](DEPLOYMENT.md) for operational contracts.

---

# 15. Audit

Clinical, administrative and financial mutations require traceability.

Audit should answer:

Who?
What?
Which tenant?
Which patient/visit?
When?
What changed?
Why, when required?

---

# 16. Payment Architecture

Payment requests originate from tenant billing context.

External gateway interaction must preserve a safe tenant reference.

Webhook:

Raw Request
→ Signature Verification
→ Payload Parse
→ Tenant Resolution
→ Tenant Validation
→ Idempotency Check
→ Tenant DB Transaction
→ Billing Update
→ Audit/Event

Never trust unsigned webhook content.

---

# 17. Scalability

Initial deployment may run:

* one or few backend instances
* PostgreSQL
* Redis
* frontend/nginx

Architecture should support later horizontal scaling.

Redis Pub/Sub enables multiple backend/WebSocket instances to coordinate.

Persistent state remains in PostgreSQL.

---

# 18. Smart Hospital Extension

Future event sources may include:

* RFID
* BLE
* UWB
* cameras
* medical devices
* kiosks
* mobile applications

These should produce operational events rather than directly modifying arbitrary database state.

Future event architecture may evolve toward:

Device/Event
→ Event Ingestion
→ Rules/AI
→ HMS Domain Service
→ PostgreSQL
→ Alert/Event Bus

---

# 19. AI Architecture Principle

AI must remain advisory unless a workflow explicitly authorizes autonomous action.

Clinical AI outputs should record:

* model
* version
* request
* result
* confidence where applicable
* doctor acceptance/rejection where applicable

Do not mix future AI implementation into OPD stabilization unless explicitly assigned.

---

# 20. Reliability Principle

Clinical and financial operations should degrade safely.

Examples:

Redis unavailable:
persist transaction, real-time notification may degrade.

WebSocket unavailable:
API remains authoritative.

Payment gateway unavailable:
invoice remains pending; do not fabricate payment.

AI unavailable:
normal clinical workflow remains usable.

Camera unavailable:
normal hospital operation remains usable.

Smart capabilities must enhance HMS, not become mandatory dependencies for core care delivery.

---

# 12. Pharmacy Domain Architecture

Pharmacy is now an approved active extension of the HMS domain platform. It retains an independent operational lifecycle and must not alter the canonical OPD Visit lifecycle.

## 12.1 Separation of clinical prescribing and inventory

The architecture must preserve this boundary:

```text
Medicine Master
→ Hospital Formulary
→ Doctor Prescription

Supplier / Purchase / GRN
→ Batch Inventory
→ Stock Ledger

Prescription + Inventory
→ Pharmacy Queue
→ Validation
→ Dispensing
→ Billing
→ Stock Deduction
```

The doctor searches the **Hospital Formulary**, not the inventory table.

An active, prescribable formulary medicine remains clinically prescribable even when hospital stock is zero. Stock availability may be displayed as operational information but must never invalidate the prescription, reduce the prescribed quantity, or force substitution. The patient may purchase unavailable medicine externally.

Inventory is never deducted when a doctor creates a prescription. Inventory is deducted only through confirmed pharmacy dispensing.

## 12.2 Pharmacy inventory principles

- Inventory is batch and location based.
- Batch expiry is mandatory where applicable.
- FEFO (First Expiry, First Out) is the default dispensing allocation strategy.
- Stock movement is recorded through an auditable stock ledger.
- Current balance must not be the only source of stock audit history.
- Expired/quarantined/recalled stock is non-dispensable.
- Stock transfer, adjustment and physical-count variance require explicit workflows and audit.

## 12.3 Pharmacy implementation roadmap

Detailed requirements are maintained under `docs/pharmacy/`:

- P25 — Medicine Master, Formulary and Prescription Integration
- P26 — Supplier, Purchase Order and GRN
- P27 — Batch Inventory, Stock Ledger and FEFO
- P28 — Pharmacy Queue, Validation and Dispensing
- P29 — Billing Integration
- P30 — Patient and Supplier Returns
- P31 — Expiry, Damage and Recall
- P32 — Stock Transfer / Multi-location
- P33 — Cycle Count / Physical Verification
- P34 — Dashboard, Alerts, Reports and Audit
