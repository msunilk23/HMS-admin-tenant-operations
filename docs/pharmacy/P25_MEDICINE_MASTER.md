# P25 — Medicine Master + Formulary + Prescription Integration

## P25.1 Repository analysis and current capability assessment
Inspect existing Phase 12 Pharmacy code, prescription models/schemas/APIs/UI, controlled diagnosis search, RBAC, tenant/facility handling, migrations, tests and dashboard failure. Report already implemented/partial/missing/incorrect. **No coding. STOP.**

## P25.2 Pharmacy data-model and migration design
Design the exact schema changes after P25.1. Reuse existing entities where possible. Produce proposed tables/columns/FKs/indexes/uniqueness/backward-compatibility/migration plan. **No migration execution until approved. STOP.**

## P25.3 Generic Medicine Master
Controlled generic code/name, description, therapeutic class, active state and audit. Unique per tenant. No destructive delete once referenced.

## P25.4 Dosage Form + Route Masters
Dosage forms support calculation type: UNIT, LIQUID, PRN, MANUAL. Routes are controlled master data.

## P25.5 Manufacturer Master
Manufacturer code/name, GSTIN, country, active state and audit.

## P25.6 Medicine Product / Brand Master
Medicine code, generic, brand, strength/unit, dosage form, default route, manufacturer, composition, HSN, GST, schedule category, controlled-drug and prescription-required metadata.

## P25.7 Hospital Formulary
Tenant/facility medicine approval with preferred, prescribable, active and effective dates. Doctor search uses formulary, not stock.

## P25.8 Controlled Medicine Search API
Search generic/brand/code/composition. Return active prescribable formulary products. Do not fake inventory quantities.

## P25.9 Prescription Builder integration
Autocomplete with explicit selection and medicine_id. Preserve an existing controlled free-text exception only if current HMS supports it; require reason and visible marking.

## P25.10 Prescription historical snapshot
Persist medicine_id plus generic/brand/strength/dosage-form/route snapshots without breaking existing prescriptions.

## P25.11 Automatic quantity calculation
For UNIT dosage forms: sum daily frequency units × duration days. Examples: 1-0-1 × 5 = 10; 1-1-1 × 5 = 15. Do not incorrectly calculate complex dosage forms.

## P25.12 Quantity override + audit
Persist auto quantity, final quantity, override flag and reason according to policy.

## P25.13 Pharmacy Admin UI
Medicine Master, Generic Medicines, Dosage Forms, Routes, Manufacturers and Formulary. Search/filter/pagination/add/edit/activate/deactivate.

## P25.14 RBAC
Use existing framework. Add equivalent granular permissions for Pharmacy master view/create/edit and formulary management.

## P25.15 Deterministic seed data
Include Paracetamol/Dolo/Crocin and representative antibiotics, PPI, antihistamine and NSAID for dev/E2E.

## P25.16 Backend/API tests
CRUD, search, inactive exclusion, tenant/facility isolation, prescription save/snapshot, calculation and override.

## P25.17 Playwright E2E
Generic search, brand search, free-text behavior, quantity calculation, override, save/reload.

## P25.18 OPD regression
Run existing registration/nurse/doctor/diagnosis/prescription regression.

## P25.19 Dashboard defect
Investigate dashboard route/API/auth/tenant/frontend rendering independently and add dashboard-load E2E.

## P25.20 Final P25 review
Full relevant tests, migration validation, code/architecture review, known limitations and P26 readiness.

## Hard acceptance rule
Zero stock never blocks prescribing; no stock is deducted by prescription creation.

After every P25.x task STOP and wait for `APPROVED - PROCEED <NEXT_TASK_ID>`.
