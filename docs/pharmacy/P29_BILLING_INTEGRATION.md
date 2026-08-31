# P29 — Pharmacy Billing Integration
Integrate confirmed fulfillment with existing HMS Billing. Target: prescription → pharmacy confirmation → billing/payment or approved credit → dispense confirmation → stock deduction. Failed/cancelled billing must not create permanent consumption. Handle partial fulfillment and idempotency. Approval-gate every task.

## P29.2 Implementation

The persisted billing boundary is now authoritative through `Invoice.pharmacy_dispense_id`, which identifies the exact `PharmacyDispense` represented by a pharmacy invoice. `PharmacyDispense.invoice_id` is retained as a reverse lookup for existing API and operational records; invoice creation writes both values together.

The tenant-schema migration `0075` conditionally adds missing linkage columns, foreign keys, indexes, and the nullable unique constraint `uq_invoices_pharmacy_dispense`. It is compatible with databases where `ensure_schema.py` previously added the columns and does not remove existing data. A single dispense can have at most one active invoice, while separate dispense events for the same prescription may have separate invoices.

Pharmacy financial lines remain in the existing canonical invoice JSON representation. P29.2 stores `dispense_item_id` and `prescription_item_id` in pharmacy line snapshots so each billed quantity can be traced to its dispense item without introducing a parallel Pharmacy-only `InvoiceItem` table.

Implemented in P29.2: persisted invoice/dispense linkage, source identity `pharmacy_dispense`, one-invoice-per-dispense protection, and migration compatibility.

## P29.3 Implementation

Pharmacy invoice prices are resolved server-side from the allocated inventory batch (`InventoryBatch.mrp`) and the linked medicine product (`MedicineProduct.gst_rate`). Client-supplied MRP, GST, discount percentage, and line total values are not authoritative. Invoice lines retain the resolved price and tax snapshot, and totals are calculated with `Decimal` and two-decimal half-up rounding.

Discounts are currently fixed at zero until a separately approved server-side discount policy exists; client-supplied non-zero discounts are rejected. Outside-purchase quantities remain excluded, and only remaining internal confirmed quantity is billable.

Implemented in P29.3: server-side batch price resolution, GST resolution, discount rejection without policy, Decimal totals, tamper-resistant financial snapshots, and regression coverage.

Future P29 tasks: approved credit, billing failure timeout automation, and P29.10 RBAC/audit hardening.

## P29.9 Implementation

The Pharmacy dispense workspace now displays hospital-supplied and outside-purchase quantities, creates the linked Pharmacy invoice from dispense-item IDs, lets the pharmacist choose cash or online payment, displays the invoice/payment state, and provides payment verification recovery for missed Razorpay callbacks. The UI no longer sends direct dispense confirmation before billing authorization; confirmation is performed by the backend payment handoff.

Implemented in P29.9: Pharmacy billing controls, payment-state display, online-payment verification recovery, billing cancellation, and preservation of the server-side dispense authorization boundary.
