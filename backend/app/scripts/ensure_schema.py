"""
ensure_schema.py — Run at every startup to guarantee all tenant schemas
have the exact columns and indexes that the SQLAlchemy models expect.

Idempotent: uses ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS so
it is safe to run on every `docker-compose up`.

Usage:
    python -m app.scripts.ensure_schema
"""
import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import AsyncSessionLocal, init_db

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Columns that every tenant table must have.
# Format: { table: [(column, DDL type + constraints + default), ...] }
# ---------------------------------------------------------------------------
TENANT_COLUMNS: dict = {
    "appointments": [
        ("uhid",              "VARCHAR(20)"),
        ("type",              "VARCHAR(20) NOT NULL DEFAULT 'walkin'"),
        ("booked_by_user_id", "UUID"),
    ],
    "visits": [
        ("uhid",          "VARCHAR(20)"),
        ("department_id", "UUID"),
    ],
    "queue_tokens": [
        ("uhid",         "VARCHAR(20)"),
        ("department_id","UUID"),
        ("doctor_id",    "UUID"),
        ("visit_id",     "UUID"),
        ("notes",        "TEXT"),
        ("cancelled_at", "TIMESTAMP WITH TIME ZONE"),
    ],
    "consultations": [
        ("uhid", "VARCHAR(20)"),
    ],
    "vitals": [
        ("uhid", "VARCHAR(20)"),
        ("bmi",  "NUMERIC(5,2)"),
    ],
    "prescriptions": [
        ("uhid", "VARCHAR(20)"),
    ],
    "lab_orders": [
        ("uhid",       "VARCHAR(20)"),
        ("status",     "VARCHAR(20) NOT NULL DEFAULT 'ordered'"),
        ("ordered_at", "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"),
        ("sample_collected_at", "TIMESTAMP WITH TIME ZONE"),
        ("processing_started_at", "TIMESTAMP WITH TIME ZONE"),
        ("result_ready_at", "TIMESTAMP WITH TIME ZONE"),
        ("verified_at", "TIMESTAMP WITH TIME ZONE"),
        ("completed_at", "TIMESTAMP WITH TIME ZONE"),
    ],
    "lab_results": [
        ("uhid",               "VARCHAR(20)"),
        ("notes",              "TEXT"),
        ("critical_flags",     "JSONB"),
        ("report_url",         "TEXT"),
        ("reported_by_user_id","UUID"),
        ("reported_at",        "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"),
        ("verified_by_user_id","UUID"),
        ("verified_at",        "TIMESTAMP WITH TIME ZONE"),
    ],
    "audit_logs": [
        ("tenant_schema",      "VARCHAR(100)"),
        ("role",               "VARCHAR(50)"),
        ("patient_id",        "UUID"),
        ("visit_id",           "UUID"),
        ("request_id",         "VARCHAR(100)"),
        ("source_ip",          "VARCHAR(45)"),
        ("reason",             "TEXT"),
        ("request_metadata",   "JSONB"),
    ],
    "pharmacy_queue": [
        ("uhid",       "VARCHAR(20)"),
        ("notes",      "TEXT"),
        ("updated_at", "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"),
        ("called_at", "TIMESTAMP WITH TIME ZONE"),
        ("dispensing_started_at", "TIMESTAMP WITH TIME ZONE"),
        ("dispensed_at", "TIMESTAMP WITH TIME ZONE"),
    ],
    "nurse_roster": [
        ("department_id",       "UUID"),
        ("substitute_user_id",  "UUID"),
        ("substitution_reason", "TEXT"),
        ("is_active",            "BOOLEAN NOT NULL DEFAULT TRUE"),
    ],
    "feedback": [
        ("channel", "VARCHAR(20) NOT NULL DEFAULT 'staff'"),
    ],
    "invoices": [
        ("uhid",               "VARCHAR(20)"),
        ("razorpay_order_id",  "VARCHAR(120)"),
        ("razorpay_payment_id","VARCHAR(120)"),
        ("source",             "VARCHAR(20) DEFAULT 'consultation'"),
        ("pharmacy_queue_id",  "UUID"),
        ("pharmacy_dispense_id","UUID"),
        ("paid_at",            "TIMESTAMP WITH TIME ZONE"),
        ("paid_amount",        "NUMERIC(10,2) NOT NULL DEFAULT 0"),
        ("receipt_number",     "VARCHAR(40)"),
    ],
    "payments": [
        ("invoice_id",         "UUID NOT NULL"),
        ("amount",             "NUMERIC(10,2) NOT NULL"),
        ("payment_method",     "VARCHAR(20) NOT NULL DEFAULT 'cash'"),
        ("status",             "VARCHAR(20) NOT NULL DEFAULT 'captured'"),
        ("transaction_reference", "VARCHAR(120)"),
        ("gateway",            "VARCHAR(30)"),
        ("notes",              "TEXT"),
        ("paid_at",            "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"),
    ],
    "refunds": [
        ("invoice_id",         "UUID NOT NULL"),
        ("amount",             "NUMERIC(10,2) NOT NULL"),
        ("reason",             "TEXT NOT NULL"),
        ("status",             "VARCHAR(20) NOT NULL DEFAULT 'completed'"),
        ("refunded_at",        "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"),
    ],
    "patients": [
        ("age",            "INTEGER"),
        ("aadhar_number",  "VARCHAR(20)"),
        ("blood_group",    "VARCHAR(10)"),
        ("insurance_provider", "VARCHAR(255)"),
        ("insurance_id",   "VARCHAR(255)"),
        ("emergency_contact_name",     "VARCHAR(200)"),
        ("emergency_contact_phone",    "VARCHAR(15)"),
        ("emergency_contact_relation", "VARCHAR(50)"),
    ],
    "doctors": [
        ("full_name",        "VARCHAR(255)"),
        ("consultation_fee", "NUMERIC(10,2) NOT NULL DEFAULT 0.0"),
        ("qualification",    "VARCHAR(500)"),
        ("experience_years", "INTEGER"),
        ("is_active",        "BOOLEAN NOT NULL DEFAULT TRUE"),
    ],
    "indents": [
        ("amount", "NUMERIC(12,2)"),
    ],
}

# ---------------------------------------------------------------------------
# Indexes that every tenant schema must have.
# Format: (table, index_name, [columns])
# ---------------------------------------------------------------------------
TENANT_INDEXES: list = [
    ("appointments",  "ix_appointments_uhid",               ["uhid"]),
    ("appointments",  "ix_appointments_patient_id",         ["patient_id"]),
    ("appointments",  "ix_appointments_doctor_id",          ["doctor_id"]),
    ("appointments",  "ix_appointments_slot_time",          ["slot_time"]),
    ("visits",        "ix_visits_patient_id",               ["patient_id"]),
    ("visits",        "ix_visits_department_id",            ["department_id"]),
    ("queue_tokens",  "ix_queue_tokens_patient_id",         ["patient_id"]),
    ("queue_tokens",  "ix_queue_tokens_uhid",               ["uhid"]),
    ("queue_tokens",  "ix_queue_tokens_visit_id",           ["visit_id"]),
    ("queue_tokens",  "ix_queue_tokens_department_id",      ["department_id"]),
    ("queue_tokens",  "ix_queue_tokens_doctor_id",          ["doctor_id"]),
    ("consultations", "ix_consultations_visit_id",          ["visit_id"]),
    ("consultations", "ix_consultations_uhid",              ["uhid"]),
    ("vitals",        "ix_vitals_visit_id",                 ["visit_id"]),
    ("vitals",        "ix_vitals_uhid",                     ["uhid"]),
    ("prescriptions", "ix_prescriptions_visit_id",          ["visit_id"]),
    ("prescriptions", "ix_prescriptions_uhid",              ["uhid"]),
    ("lab_orders",    "ix_lab_orders_visit_id",             ["visit_id"]),
    ("lab_orders",    "ix_lab_orders_uhid",                 ["uhid"]),
    ("lab_results",   "ix_lab_results_lab_order_id",        ["lab_order_id"]),
    ("lab_results",   "ix_lab_results_uhid",                ["uhid"]),
    ("invoices",      "ix_invoices_visit_id",               ["visit_id"]),
    ("invoices",      "ix_invoices_uhid",                   ["uhid"]),
    ("invoices",      "ix_invoices_pharmacy_dispense_id",   ["pharmacy_dispense_id"]),
    ("pharmacy_queue","ix_pharmacy_queue_prescription_id",  ["prescription_id"]),
    ("pharmacy_queue","ix_pharmacy_queue_uhid",             ["uhid"]),
    ("patients",      "ix_patients_uhid",                   ["uhid"]),
    ("patients",      "ix_patients_phone",                  ["phone"]),
    ("indents",       "ix_indents_indent_number",           ["indent_number"]),
    ("indents",       "ix_indents_requested_by_id",         ["requested_by_id"]),
    ("indents",       "ix_indents_status",                  ["status"]),
]


async def _ensure_for_schema(session: AsyncSession, schema: str) -> None:
    """Apply all ADD COLUMN IF NOT EXISTS and CREATE INDEX IF NOT EXISTS for one schema."""
    await session.execute(text(f'SET search_path TO "{schema}", public'))

    tables_result = await session.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
    ), {"schema": schema})
    existing_tables = {row[0] for row in tables_result}

    # ── Columns ─────────────────────────────────────────────────────────────
    for table, columns in TENANT_COLUMNS.items():
        if table not in existing_tables:
            continue
        for col_name, col_ddl in columns:
            sql = (
                f'ALTER TABLE "{schema}"."{table}" '
                f'ADD COLUMN IF NOT EXISTS "{col_name}" {col_ddl};'
            )
            await session.execute(text(sql))

    # ── Indexes ──────────────────────────────────────────────────────────────
    for table, idx_name, idx_cols in TENANT_INDEXES:
        if table not in existing_tables:
            continue
        cols_sql = ", ".join(f'"{c}"' for c in idx_cols)
        sql = (
            f'CREATE INDEX IF NOT EXISTS "{idx_name}" '
            f'ON "{schema}"."{table}" ({cols_sql});'
        )
        await session.execute(text(sql))

    # ── Backfill uhid where NULL from patients ───────────────────────────────
    patient_linked = [
        ("appointments", "patient_id"),
        ("queue_tokens",  "patient_id"),
    ]
    for table, fk_col in patient_linked:
        if table not in existing_tables:
            continue
        await session.execute(text(
            f'UPDATE "{schema}"."{table}" t '
            f'SET uhid = p.uhid '
            f'FROM "{schema}".patients p '
            f'WHERE t.{fk_col} = p.id AND t.uhid IS NULL'
        ))

    visit_linked = [
        "consultations", "vitals", "prescriptions", "lab_orders", "invoices",
    ]
    for table in visit_linked:
        if table not in existing_tables:
            continue
        await session.execute(text(
            f'UPDATE "{schema}"."{table}" t '
            f'SET uhid = p.uhid '
            f'FROM "{schema}".visits v '
            f'JOIN "{schema}".patients p ON v.patient_id = p.id '
            f'WHERE t.visit_id = v.id AND t.uhid IS NULL'
        ))

    # lab_results: backfill via lab_orders → visits → patients
    if "lab_results" in existing_tables:
        await session.execute(text(
            f'UPDATE "{schema}".lab_results t '
            f'SET uhid = p.uhid '
            f'FROM "{schema}".lab_orders lo '
            f'JOIN "{schema}".visits v ON lo.visit_id = v.id '
            f'JOIN "{schema}".patients p ON v.patient_id = p.id '
            f'WHERE t.lab_order_id = lo.id AND t.uhid IS NULL'
        ))

    # pharmacy_queue: backfill via prescriptions → visits → patients
    if "pharmacy_queue" in existing_tables:
        await session.execute(text(
            f'UPDATE "{schema}".pharmacy_queue t '
            f'SET uhid = p.uhid '
            f'FROM "{schema}".prescriptions rx '
            f'JOIN "{schema}".visits v ON rx.visit_id = v.id '
            f'JOIN "{schema}".patients p ON v.patient_id = p.id '
            f'WHERE t.prescription_id = rx.id AND t.uhid IS NULL'
        ))

    # ── Safety fallback: stamp any still-NULL uhid as 'UNKNOWN' ─────────────
    # Prevents ALTER COLUMN SET NOT NULL from failing on orphaned rows.
    all_uhid_tables = [
        "appointments", "visits", "queue_tokens", "consultations", "vitals",
        "prescriptions", "lab_orders", "lab_results", "pharmacy_queue", "invoices",
    ]
    for table in all_uhid_tables:
        if table not in existing_tables:
            continue
        await session.execute(text(
            f'UPDATE "{schema}"."{table}" SET uhid = \'UNKNOWN\' WHERE uhid IS NULL'
        ))

    # ── Enforce NOT NULL on uhid in every table that has it ─────────────────
    for table in all_uhid_tables:
        if table not in existing_tables:
            continue
        await session.execute(text(
            f'ALTER TABLE "{schema}"."{table}" ALTER COLUMN uhid SET NOT NULL'
        ))

    await session.commit()
    log.info("ensure_schema: schema '%s' ✓", schema)


async def ensure_all_schemas() -> None:
    await init_db()

    async with AsyncSessionLocal() as session:
        # Fetch all tenant schemas from public
        await session.execute(text("SET search_path TO public"))
        result = await session.execute(text("SELECT schema_name FROM public.tenants"))
        schemas = [row[0] for row in result]

    if not schemas:
        log.warning("ensure_schema: no tenant schemas found — skipping")
        return

    for schema in schemas:
        async with AsyncSessionLocal() as session:
            try:
                await _ensure_for_schema(session, schema)
            except Exception:
                log.exception("ensure_schema: failed for schema '%s'", schema)
                raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(ensure_all_schemas())
    print("✅ Schema ensure complete.")
