# P29 — Pharmacy Billing Integration
Integrate confirmed fulfillment with existing HMS Billing. Target: prescription → pharmacy confirmation → billing/payment or approved credit → dispense confirmation → stock deduction. Failed/cancelled billing must not create permanent consumption. Handle partial fulfillment and idempotency. Approval-gate every task.
