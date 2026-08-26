# Pharmacy Master Requirements

## Objective
Implement an auditable, multi-tenant Pharmacy subsystem integrated with OPD prescription, procurement, inventory, dispensing, billing, returns and stock control.

## End-to-end flow
Medicine Master → Supplier Master → Purchase Order → GRN → Batch/Expiry → Inventory → Doctor Prescription → Pharmacy Queue → Validation → Dispensing → Billing → Stock Deduction

## Additional operations
- Patient Return
- Supplier Return
- Damaged / Expired / Recalled Stock
- Stock Adjustment
- Stock Transfer
- Cycle Count
- Physical Verification

## Clinical prescribing rule
Hospital stock never blocks an active/prescribable formulary medicine. If unavailable internally, the prescription remains valid and the patient may purchase it outside.

## Quantity
For supported UNIT dosage forms:
`quantity = total daily frequency units × duration in days`

Doctor override is allowed only through controlled/audited behavior.

## Inventory
Batch/location based; expiry controlled; FEFO default; stock ledger auditable; no deduction at prescription creation.

## Governance
Execute P25-P34 in order. Each Pxx.x task requires test/report/STOP/explicit approval.
