# Shankar Super Speciality Hospital — OPD Management System
## Master Plan v1.0

---

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI (async), SQLAlchemy 2.x (async), Alembic |
| Frontend | React 18, Vite, TypeScript, shadcn/ui, Tailwind CSS |
| Database | PostgreSQL 16 (schema-per-tenant multi-tenancy) |
| Cache / Pub-Sub | Redis 7 |
| Real-time | WebSockets (FastAPI) + Redis pub/sub |
| Auth | JWT (HS256), RBAC |
| Containerisation | Docker Compose (dev) + Kubernetes (prod) |
| Reverse Proxy | Nginx |

---

### Multi-Tenancy Model

- **Schema-per-hospital**: every hospital gets its own PostgreSQL schema (e.g. `shankar`, `apollo`)
- `public` schema holds cross-tenant tables: `tenants`, `users`
- Tenant is resolved from JWT claim on every request
- Middleware executes `SET search_path TO '{tenant_schema}'` before each DB operation via SQLAlchemy + Python `contextvars`
- Alembic custom `env.py` runs schema migrations across **all** registered tenant schemas automatically

---

### RBAC Roles

| Role | Description |
|------|-------------|
| `super_admin` | Cross-tenant platform administrator |
| `hospital_admin` | Full access within one hospital tenant |
| `receptionist` | Patient registration, appointments, queue |
| `doctor` | Consultation, prescriptions, lab orders |
| `nurse` | Vitals recording, duty roster |
| `billing_officer` | Invoices, payments |
| `pharmacist` | Prescription queue, fulfilment |
| `lab_technician` | Lab orders, result entry |

---

### Screens — v1 (14 Screens)

| # | Screen | Primary Role |
|---|--------|-------------|
| 1 | Patient UHID Registration & Search | Receptionist |
| 2 | Appointment Booking & Calendar | Receptionist / Patient |
| 3 | OPD Queue Dashboard — Reception | Receptionist |
| 4 | Token Display Board — TV Screen | Public |
| 5 | Nurse Pre-Consult Vitals | Nurse |
| 6 | Nurse Duty Roster & Room Assignment | Nurse Head |
| 7 | Doctor Consultation (Patient Chart) | Doctor |
| 8 | Prescription Builder | Doctor |
| 9 | Lab Investigation Orders & Result Sync | Doctor / Lab Tech |
| 10 | Pharmacy Prescription Queue & Fulfilment | Pharmacist |
| 11 | Billing — Invoice & Payment | Billing Officer |
| 12 | Feedback Automation | Auto / Admin |
| 13 | Admin Command Center Dashboard | Hospital Admin |
| 14 | Doctor & Department Management | Hospital Admin |

---

### Database Schema Design

#### Shared — `public` schema

```
tenants          id, schema_name, hospital_name, contact_email, is_active, created_at
users            id, tenant_id, email, hashed_password, full_name, role, is_active, created_at
```

#### Per-Tenant Schema (e.g. `shankar`)

```
departments      id, name, description, is_active
doctors          id, user_id, name, specialization, department_id, consultation_fee, is_active
patients         id, uhid, first_name, last_name, dob, gender, phone, email, address,
                 blood_group, insurance_provider, insurance_id, created_at
appointments     id, patient_id, doctor_id, slot_time, status, type, notes, created_at
                 status: scheduled | confirmed | checked_in | completed | cancelled | no_show
                 type:   walkin | pre_booked
queue_tokens     id, patient_id, appointment_id, token_no, queue_type, priority, status, issued_at, called_at
                 queue_type: registration | vitals | consultation | pharmacy | billing
                 priority:   emergency | senior_citizen | normal
                 status:     waiting | called | in_progress | completed | skipped
visits           id, patient_id, doctor_id, appointment_id, status, created_at, closed_at
                 status: registered | vitals_done | in_consultation | prescription_done | billing_pending | closed
vitals           id, visit_id, bp_systolic, bp_diastolic, temperature, weight, height,
                 spo2, pulse, recorded_by_user_id, recorded_at
consultations    id, visit_id, chief_complaint, history, examination,
                 diagnosis_icd10 (jsonb), notes, follow_up_date
prescriptions    id, visit_id, medicines (jsonb), instructions, created_at
lab_orders       id, visit_id, tests (jsonb), status, ordered_at
                 status: ordered | sample_collected | processing | resulted
lab_results      id, lab_order_id, results (jsonb), reported_by_user_id, reported_at
pharmacy_queue   id, prescription_id, status, notes, updated_at
                 status: pending | preparing | ready | partial | dispensed
invoices         id, visit_id, line_items (jsonb), subtotal, discount, tax, total,
                 payment_method, status, paid_at
                 payment_method: cash | upi | card | insurance
                 status: draft | paid | cancelled
feedback         id, visit_id, rating (1-5), comments, submitted_at
nurse_roster     id, user_id, date, shift, room, assigned_doctor_id, is_present
                 shift: morning | afternoon | night
audit_logs       id, user_id, action, resource_type, resource_id,
                 old_value (jsonb), new_value (jsonb), ip_address, timestamp
```

---

### WebSocket Events (Redis pub/sub)

| Channel | Triggered By | Consumed By |
|---------|-------------|-------------|
| `{tenant}:queue:update` | Token status change | Reception dashboard, TV display board |
| `{tenant}:appointment:update` | Booking / cancel / delay | Reception, patient |
| `{tenant}:visit:update` | Stage transition (vitals done → consult done) | Nurse screen, doctor screen |
| `{tenant}:pharmacy:update` | Prescription ready / partial / dispensed | Pharmacist, billing |
| `{tenant}:lab:update` | Results uploaded | Doctor chart |

---

### Implementation Phases

#### Phase 0 — Foundation *(blocks all subsequent phases)*
- [ ] Monorepo root scaffold + `.gitignore`, `.env.example`
- [ ] Docker Compose: PostgreSQL + Redis + pgAdmin + Nginx + backend + frontend
- [ ] FastAPI app: pydantic-settings config, async SQLAlchemy engine, lifespan startup
- [ ] Tenant middleware: JWT → `contextvars` → `SET search_path`
- [ ] JWT auth: login, refresh token, bcrypt password hashing
- [ ] RBAC: `require_role()` dependency decorator
- [ ] Alembic: `public` schema migration (tenants + users); multi-tenant `env.py`
- [ ] Tenant provisioning API endpoint (`POST /tenants`)
- [ ] Seed script: Shankar Super Speciality Hospital tenant + default admin user
- [ ] React: Vite + TypeScript strict + shadcn/ui + Tailwind + React Router v6
- [ ] TanStack Query v5 + Zustand + React Hook Form + Zod + axios client
- [ ] Login page + JWT interceptor + protected route wrapper + role guard
- [ ] App shell: sidebar navigation + top header + breadcrumb

#### Phase 1 — Walk-in Core Loop *(Sprint 1 — primary milestone)*
- [ ] Patient UHID Registration & Search screen
- [ ] Token allocation engine (priority: emergency > senior > normal)
- [ ] OPD Queue Dashboard — Reception (real-time via WebSocket)
- [ ] Token Display Board — TV screen (WebSocket driven, public route)
- [ ] Nurse Vitals screen (pick next patient → record vitals → push to doctor queue)
- [ ] Doctor Consultation screen (patient chart, vitals, SOAP notes, ICD-10)
- [ ] Prescription Builder (medicine search, dosage/frequency/duration, PDF export)
- [ ] Billing screen (invoice line items, UPI/Card/Cash, visit closure)

#### Phase 2 — Appointments & Online Check-in
- [ ] Doctor & Department Management (admin CRUD)
- [ ] Appointment Booking & Calendar (slot availability, reschedule, cancel, delay alerts)
- [ ] Check-in → queue insertion flow (appointment → token auto-creation)

#### Phase 3 — Clinical Extensions
- [ ] Lab Investigation Orders & Result Sync
- [ ] Pharmacy Queue & Fulfilment screen
- [ ] Nurse Duty Roster & Room Assignment

#### Phase 4 — Intelligence & Completion
- [ ] Admin Command Center Dashboard (KPI tiles + Recharts time-series charts)
- [ ] Feedback Automation (trigger on visit closure → SMS/WhatsApp link → analytics)

---

### Out of Scope — v1
- IoT / BLE / RFID hardware integrations
- AI CCTV (theft monitoring, cleaning detection)
- Emergency triage override
- IPD, OT, ER modules
- External pharmacy routing
- Patient-facing mobile app

---

### Verification Checklist

- [ ] `docker compose up` → all 6 services healthy (backend, frontend, postgres, redis, nginx, pgadmin)
- [ ] Login returns valid JWT; Shankar tenant schema (`shankar`) visible in PostgreSQL
- [ ] Full walk-in loop completable without errors end-to-end
- [ ] Two browser tabs show real-time queue updates simultaneously (WebSocket)
- [ ] Appointment booked online → appears in queue on patient arrival
- [ ] Lab result saved → visible on doctor chart immediately (WebSocket)
- [ ] Invoice paid → feedback link triggered automatically
- [ ] All API routes return `401 Unauthorized` without valid JWT
- [ ] Cross-tenant isolation: user from tenant A cannot access tenant B data
- [ ] Audit log entry created for every create/update/delete operation
