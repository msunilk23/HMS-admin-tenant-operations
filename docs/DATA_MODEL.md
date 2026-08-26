# HMS Core Data Model

## 1. Data Model Principle

The data model must distinguish:

* Person/Patient
* Booking
* Encounter
* Clinical records
* Operational workflows
* Financial workflows

The OPD encounter backbone is:

`visit_id`

---

# 2. High-Level Relationship

Patient
│
├── Appointment
│       │
│       └── Visit
│
└────────── Visit
│
├── QueueToken
├── Vitals
├── Consultation
│      │
│      ├── Prescription
│      │       └── PrescriptionItem
│      │
│      └── LabOrder
│
├── Invoice
└── Feedback

---

# 3. Patient

Represents the patient independent of individual encounters.

Typical fields:

* id
* uhid
* first_name/full_name according to current model
* DOB
* age where required by current business model
* gender
* mobile
* email
* address
* Aadhaar where legally/business appropriate
* emergency contact
* blood group
* insurance information
* active/inactive
* created_at
* updated_at

UHID should uniquely identify the patient within the intended business scope.

Patient data must not be duplicated merely because the patient returns for another visit.

---

# 4. Appointment

Represents a scheduled booking.

Typical linkage:

* patient_id
* doctor_id
* department_id
* appointment date/time
* status
* booking metadata

Appointment is optional for a Visit.

Walk-in Visit:

`appointment_id = NULL`

Appointment check-in:

`visit.appointment_id = appointment.id`

---

# 5. Visit

Represents one OPD encounter.

Typical fields:

* id
* patient_id
* appointment_id nullable
* doctor_id
* department_id
* visit type
* canonical status
* arrival/registration timestamps
* created_by
* created_at
* updated_at

Canonical status:

* REGISTERED
* WAITING_FOR_NURSE
* IN_PRE_VITAL
* WAITING_FOR_DOCTOR
* IN_CONSULTATION
* CONSULTATION_COMPLETED
* CLOSED
* CANCELLED

Visit status represents clinical OPD lifecycle only.

---

# 6. QueueToken

Represents queue participation.

Important fields:

* id
* visit_id
* patient_id where retained for convenience
* appointment_id where retained
* token_no
* queue_type
* priority
* status
* issued_at
* called_at
* completed_at

`visit_id` is the primary encounter linkage.

Legacy records may temporarily have nullable visit_id.

New OPD queue records should populate visit_id.

---

# 7. Vitals

Linked directly to Visit.

Typical fields:

* id
* visit_id
* temperature
* pulse
* respiratory_rate
* bp_systolic
* bp_diastolic
* spo2
* pain_score
* height_cm
* weight_kg
* bmi
* blood_glucose
* chief_complaint
* allergies
* known_no_allergies
* general_condition
* level_of_consciousness
* nurse_notes
* recorded_by
* started_at
* completed_at
* status

BMI is derived from height/weight.

---

# 8. Consultation

Linked to Visit.

Typical fields:

* id
* visit_id
* doctor_id
* chief_complaint
* history
* examination
* provisional_diagnosis
* final_diagnosis
* ICD-10
* advice
* notes
* follow_up
* status
* started_at
* completed_at
* completed_by

Consultation status may include:

* DRAFT
* IN_PROGRESS
* COMPLETED
* AMENDED

Completed records require controlled amendment.

---

# 9. Prescription

Prescription Header:

* id
* visit_id
* consultation_id
* doctor_id
* status
* created_at

Prescription must remain traceable to its encounter.

---

# 10. PrescriptionItem

One prescription has multiple items.

Typical:

* id
* prescription_id
* medicine_id
* medicine_name_snapshot
* strength
* dose
* route
* frequency
* duration
* quantity
* instructions

Structured items are preferred for Pharmacy integration.

---

# 11. LabOrder

Typical:

* id
* visit_id
* consultation_id
* doctor_id
* test_id/test reference
* priority
* specimen
* status
* ordered_at
* collected_at
* processing timestamps
* result timestamps
* sample_collected_at
* processing_started_at
* result_ready_at
* verified_at
* completed_at

LabOrder status is independent of Visit status.

---

# 12. LabResult

Where separated from LabOrder:

* id
* lab_order_id
* result
* units
* reference range
* abnormal flag
* entered_by
* verified_by
* result_at
* verified_at

The exact structure may depend on future LIS integration.

---

# 13. Pharmacy Workflow

Pharmacy operational records should reference:

* visit_id
* prescription_id
* prescription item where appropriate

Dispensing must not be represented using Visit status.

Future Pharmacy entities may include:

* Medicine
* Inventory
* Batch
* StockTransaction
* Supplier
* PurchaseOrder
* GRN
* Dispense
* DispenseItem
* Return
* Adjustment

These are future/extended scope unless explicitly assigned.

---

# 14. Invoice

Invoice is linked to Visit where applicable.

Typical:

* id
* visit_id
* patient_id
* invoice number
* subtotal
* discount
* tax
* total
* paid amount
* balance
* status
* created_at

Invoice status is independent from Visit status.

---

# 15. Invoice Items

Prefer structured billing items.

Typical:

* invoice_id
* service/item type
* reference id
* description
* quantity
* unit price
* discount
* tax
* amount

Potential sources:

* registration
* consultation
* lab
* procedure
* Pharmacy
* other services

---

# 16. Payment

Payment should be independently recorded.

Typical:

* id
* invoice_id
* amount
* payment method
* gateway
* gateway order id
* gateway payment id
* status
* transaction reference
* paid_at
* created_at

Payment webhook processing must be idempotent.

---

# 17. Feedback

Linked to Visit.

Typical:

* id
* visit_id
* patient_id where useful
* rating
* comments
* channel
* link_sent_at
* submitted_at

Feedback channel values are `qr`, `sms`, `whatsapp`, `kiosk`, or `staff`. One feedback row is allowed per Visit.

Future escalation logic may reference feedback without changing the clinical Visit.

---

# 18. Nurse Roster

Typical:

* id
* nurse_id
* date
* shift
* department_id
* room
* doctor_id
* attendance status
* substitution
* active

Roster entries also store `substitute_user_id` and `substitution_reason`, and new entries require a department.

Roster should support future utilization calculations.

---

# 19. AuditLog

Typical:

* id
* tenant
* user_id
* role
* action
* entity_type
* entity_id
* visit_id
* old_value
* new_value
* reason
* timestamp
* request metadata

Do not store secrets.

---

# 20. Tenant Features

Represents enabled HMS capabilities per hospital.

Typical:

* tenant_id
* feature
* enabled
* configuration
* updated_at

PostgreSQL is authoritative.

Redis may cache.

---

# 21. Referential Integrity

Prefer explicit foreign keys.

Important examples:

Visit.patient_id → Patient.id

Visit.appointment_id → Appointment.id

QueueToken.visit_id → Visit.id

Vitals.visit_id → Visit.id

Consultation.visit_id → Visit.id

Prescription.visit_id → Visit.id

LabOrder.visit_id → Visit.id

Invoice.visit_id → Visit.id

Feedback.visit_id → Visit.id

Avoid business logic based solely on matching names, dates or patient IDs where an encounter FK is available.

---

# 22. Deletion Policy

Clinical and financial records should generally not be physically deleted as normal workflow.

Prefer:

* cancelled
* inactive
* voided
* amended
* soft deletion where appropriate

Preserve audit/history.

Hard deletion of clinical or financial data requires explicit architectural approval.

---

# 23. Timestamp Policy

Use reliable timestamps for clinical and operational events.

Do not rely solely on generic:

`created_at`

for workflow analytics.

Capture semantic timestamps such as:

* arrived_at
* nurse_queue_at
* nurse_called_at
* pre_vital_started_at
* pre_vital_completed_at
* doctor_queue_at
* doctor_called_at
* consultation_started_at
* consultation_completed_at
* payment_at
* dispensed_at

Visit stores semantic registration, nurse, doctor, consultation, and billing timestamps. The visit TAT endpoint calculates durations from these persisted values and downstream lab/pharmacy/billing timestamps.

These timestamps form the foundation for TAT and SLA analytics.

---

# 24. Future Extension

The encounter architecture should later support:

Patient
→ OPD Visit

Patient
→ IP Admission

Patient
→ ER Encounter

Patient
→ OT Episode

Patient
→ Home Care Encounter

Do not force IP/ER/OT concepts into OPD Visit prematurely.

A future generalized Encounter abstraction may be introduced only after requirements are sufficiently defined.

---

# 20. Expanded Pharmacy Data Model

The original Pharmacy section is the high-level foundation. The approved P25-P34 Pharmacy extension uses the following domain entities, subject to repository analysis and task-level approval before creation.

## 20.1 Clinical pharmacy masters

- `medicine_generic`
- `medicine_dosage_form`
- `medicine_route`
- `manufacturer`
- `medicine_master`
- `medicine_formulary`

## 20.2 Procurement

- `supplier`
- `purchase_order`
- `purchase_order_item`
- `goods_receipt`
- `goods_receipt_item`

## 20.3 Inventory

- `pharmacy_location`
- `inventory_batch`
- `stock_transaction`

## 20.4 Dispensing and returns

- `pharmacy_dispense`
- `pharmacy_dispense_item`
- `patient_return`
- `patient_return_item`
- `supplier_return`
- `supplier_return_item`

## 20.5 Stock control

- `stock_transfer`
- `stock_transfer_item`
- `stock_count`
- `stock_count_item`
- `stock_adjustment`
- `pharmacy_alert`

## 20.6 PrescriptionItem extension

Prescriptions must preserve the selected controlled medicine reference and a historical snapshot so later Medicine Master changes do not rewrite clinical history.

Add/reuse equivalent fields as appropriate:

- `medicine_id`
- `generic_name_snapshot`
- `brand_name_snapshot`
- `strength_snapshot`
- `dosage_form_snapshot`
- `route_snapshot`
- `dose`
- `frequency`
- `duration`
- `quantity_auto_calculated`
- `quantity_final`
- `quantity_overridden`
- `quantity_override_reason`
- `food_instruction`
- `instructions`

For supported UNIT dosage forms:

`quantity = sum(daily frequency units) × duration_in_days`

Complex liquids, injections, creams, PRN and variable dosing must not be incorrectly auto-calculated.

## 20.7 Stock boundary

Prescription creation creates no stock transaction.

Only confirmed dispensing may create `DISPENSE` stock movement. Future stock transaction types include purchase, return, transfer, adjustment, expiry, damage and cycle-count adjustment.

Detailed entity requirements are maintained in `docs/pharmacy/`.
