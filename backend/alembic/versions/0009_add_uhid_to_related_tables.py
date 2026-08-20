"""Add uhid to all patient-related tables for fast search/audit."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    tables = [
        "visits",
        "queue_tokens",
        "appointments",
        "consultations",
        "vitals",
        "prescriptions",
        "lab_orders",
        "lab_results",
        "pharmacy_queue",
        "invoices",
    ]
    for table in tables:
        op.add_column(table, sa.Column("uhid", sa.String(20), nullable=True, index=True))

    # Backfill existing records
    bind.execute(text(
        "UPDATE visits SET uhid = p.uhid FROM patients p WHERE visits.patient_id = p.id"
    ))
    bind.execute(text(
        "UPDATE queue_tokens SET uhid = p.uhid FROM patients p WHERE queue_tokens.patient_id = p.id"
    ))
    bind.execute(text(
        "UPDATE appointments SET uhid = p.uhid FROM patients p WHERE appointments.patient_id = p.id"
    ))
    for table in ("consultations", "vitals", "prescriptions", "lab_orders", "invoices"):
        bind.execute(text(
            f"UPDATE {table} SET uhid = p.uhid "
            f"FROM visits v JOIN patients p ON v.patient_id = p.id "
            f"WHERE {table}.visit_id = v.id"
        ))
    bind.execute(text(
        "UPDATE lab_results SET uhid = p.uhid "
        "FROM lab_orders lo "
        "JOIN visits v ON lo.visit_id = v.id "
        "JOIN patients p ON v.patient_id = p.id "
        "WHERE lab_results.lab_order_id = lo.id"
    ))
    bind.execute(text(
        "UPDATE pharmacy_queue SET uhid = p.uhid "
        "FROM prescriptions rx "
        "JOIN visits v ON rx.visit_id = v.id "
        "JOIN patients p ON v.patient_id = p.id "
        "WHERE pharmacy_queue.prescription_id = rx.id"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    for table in (
        "visits", "queue_tokens", "appointments", "consultations",
        "vitals", "prescriptions", "lab_orders", "lab_results",
        "pharmacy_queue", "invoices",
    ):
        op.drop_column(table, "uhid")
