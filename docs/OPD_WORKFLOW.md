# HMS OPD Workflow

## 1. Objective

Define the authoritative end-to-end OPD business workflow.

This document describes business flow.

Implementation rules remain governed by:

`.github/copilot-instructions.md`

---

# 2. Core Encounter Model

Patient is the person.

Appointment is an optional booking.

Visit is the actual OPD encounter.

QueueToken represents operational queue participation.

The primary encounter relationship is:

Patient
→ Appointment (optional)
→ Visit

All encounter-specific clinical and operational records should resolve to `visit_id`.

---

# 3. Canonical OPD Lifecycle

REGISTERED

↓

WAITING_FOR_NURSE

↓

IN_PRE_VITAL

↓

WAITING_FOR_DOCTOR

↓

IN_CONSULTATION

↓

CONSULTATION_COMPLETED

↓

CLOSED

Optional terminal state:

CANCELLED

---

# 4. Walk-In

Receptionist selects:

Register Visit
→ Walk-In

Then:

Search Patient

If found:

Select Patient

If not found:

Register Patient

Then:

Select Department
→ Select Doctor
→ Create Visit
→ Create Queue Token
→ WAITING_FOR_NURSE

---

# 5. Appointment Check-In

Receptionist selects:

Register Visit
→ Appointment

Then:

Select Date
→ Find Appointment
→ Select Appointment
→ Check-In

System:

Creates Visit linked to Appointment
→ Creates Queue Token
→ WAITING_FOR_NURSE

Appointment check-in must not directly enter Doctor Queue.

---

# 6. Nurse Queue

Nurse sees authorized waiting patients.

State:

WAITING_FOR_NURSE

Nurse:

Call Patient
→ Start Pre-Vitals

System transitions:

WAITING_FOR_NURSE
→ IN_PRE_VITAL

Capture:

* nurse
* called timestamp
* pre-vital start timestamp

---

# 7. Pre-Vitals

Nurse records:

* temperature
* pulse
* respiratory rate
* BP
* SpO2
* pain score
* height
* weight
* BMI
* glucose
* chief complaint
* allergies
* general condition
* consciousness
* nurse notes

Draft may be saved.

Draft does not move the patient.

On Complete:

validate mandatory observations

then:

IN_PRE_VITAL
→ WAITING_FOR_DOCTOR

Capture completion timestamp.

---

# 8. Doctor Queue

Doctor sees authorized patients assigned to them.

State:

WAITING_FOR_DOCTOR

Doctor:

Call Patient
→ Open Consultation

System:

WAITING_FOR_DOCTOR
→ IN_CONSULTATION

Capture:

* doctor call time
* consultation start time

---

# 9. Consultation

Doctor may record:

* chief complaint
* history
* examination
* diagnosis
* ICD-10
* advice
* prescription
* lab orders
* follow-up
* notes

Consultation may be saved as Draft.

On Complete:

IN_CONSULTATION
→ CONSULTATION_COMPLETED

Completed clinical documentation requires controlled amendment rather than silent overwrite.

---

# 10. Downstream Workflows

After/during consultation, independent workflows may be created.

Visit
├── Prescription → Pharmacy
├── LabOrder → Lab
├── Procedures
└── Invoice → Billing

These workflows do not replace the Visit's clinical state.

---

# 11. Pharmacy

Prescription enters Pharmacy independently.

Example:

PENDING
→ CALLED
→ DISPENSING
→ DISPENSED

Pharmacy may also use:

* PARTIALLY_DISPENSED
* OUT_OF_STOCK
* CANCELLED

---

# 12. Lab

Lab Order lifecycle:

ORDERED
→ SAMPLE_PENDING
→ SAMPLE_COLLECTED
→ PROCESSING
→ RESULT_READY
→ VERIFIED
→ COMPLETED

Results remain linked to the originating Visit.

---

# 13. Feedback

Feedback is unique per Visit and records:

* rating from 1 to 5
* comments
* channel (`qr`, `sms`, `whatsapp`, `kiosk`, or `staff`)
* submitted timestamp
* link-sent timestamp

Feedback does not change Visit status.

---

# 14. Billing

Billing lifecycle is independent.

Typical:

DRAFT/PENDING
→ PARTIALLY_PAID
→ PAID

Additional:

CANCELLED
REFUNDED

Payment state must never be inferred solely from Visit status.

---

# 15. Visit Closure

CONSULTATION_COMPLETED means the doctor's clinical consultation is complete.

CLOSED means the OPD encounter has reached the configured business closure condition.

Closure rules should remain explicit and configurable rather than being implicitly driven by Pharmacy or Lab state.

---

# 16. Cancellation

Cancellation must:

* identify exact visit
* use visit_id
* record reason
* record user
* record timestamp
* cancel applicable queue participation
* preserve history

Cancellation must not delete the encounter.

---

# 17. Real-Time Events

Publish appropriate tenant-isolated events for:

* registration
* queue entry
* patient call
* pre-vitals start
* pre-vitals completion
* doctor call
* consultation start
* consultation completion
* Pharmacy
* Lab
* Billing

WebSocket events improve UX but do not replace persisted state.

---

# 18. Operational Metrics

The workflow must allow calculation of:

* registration TAT
* nurse waiting time
* pre-vitals duration
* doctor waiting time
* consultation duration
* total OPD TAT
* Pharmacy wait
* Lab wait
* Billing wait

These metrics will later support Smart Hospital optimization.

---

# 11.1 Pharmacy Prescription and Stock Boundary

The Pharmacy lifecycle above remains independent of Visit status. The expanded Pharmacy implementation adds a strict separation between clinical prescription and hospital fulfillment.

```text
Doctor Prescription
       ↓
Active/prescribable formulary medicine?
       ├── No  → controlled non-formulary/free-text exception if policy permits
       └── Yes → prescription remains valid
                    ↓
              Hospital stock check
                 ┌──┴──┐
           Available   Unavailable
               ↓           ↓
         Pharmacy       Patient may
         fulfillment    purchase outside
```

**Hard rule:** inventory availability is never a clinical prescription validation rule.

Therefore:

- zero stock must not block Save Prescription;
- prescribed quantity must not be reduced to hospital stock;
- substitution must not occur silently;
- stock must not be deducted at prescription creation;
- partial/no internal fulfillment must preserve the original prescription;
- outside purchase is a fulfillment outcome, not a prescription failure.

For supported unit medicines, prescription quantity should be automatically calculated from frequency and duration, with controlled/audited override.
