# OPD State Diagrams

## Visit lifecycle

```mermaid
stateDiagram-v2
    [*] --> REGISTERED
    REGISTERED --> WAITING_FOR_NURSE
    WAITING_FOR_NURSE --> IN_PRE_VITAL
    IN_PRE_VITAL --> WAITING_FOR_DOCTOR
    WAITING_FOR_DOCTOR --> IN_CONSULTATION
    IN_CONSULTATION --> CONSULTATION_COMPLETED
    CONSULTATION_COMPLETED --> CLOSED
    REGISTERED --> CANCELLED
    WAITING_FOR_NURSE --> CANCELLED
    IN_PRE_VITAL --> CANCELLED
    IN_CONSULTATION --> CANCELLED
```

## Independent workflows

```mermaid
flowchart LR
    V[Visit] --> P[Prescription]
    P --> PQ[Pharmacy queue]
    V --> L[Lab order]
    V --> I[Invoice]
    I --> PAY[Payment records]
    V --> F[Feedback]
    V --> T[TAT timestamps]
```

Pharmacy, lab, billing, feedback, and TAT state never replace the canonical Visit status. Completed clinical documentation requires controlled amendment. Payment webhooks are signature-verified and idempotent. Feedback is unique per visit.
