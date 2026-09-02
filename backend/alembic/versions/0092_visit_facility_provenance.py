"""Make Visit the persisted source of clinical facility provenance.

Revision ID: 0092
Revises: 0091
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "0092"
down_revision = "0091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    schema = bind.execute(text("SELECT current_schema()" )).scalar_one()
    if schema == "public":
        return

    tenant_id = bind.execute(
        text("SELECT id FROM public.tenants WHERE schema_name = :schema"),
        {"schema": schema},
    ).scalar_one()
    op.add_column("visits", sa.Column("facility_id", sa.UUID(), nullable=True))
    bind.execute(text("UPDATE visits SET facility_id = :facility_id"), {"facility_id": tenant_id})
    op.alter_column("visits", "facility_id", nullable=False)
    op.create_index("ix_visits_facility_id", "visits", ["facility_id"])
    bind.execute(text("""
        UPDATE lab_orders
        SET facility_id = visits.facility_id
        FROM visits
        WHERE lab_orders.visit_id = visits.id
    """))


def downgrade() -> None:
    bind = op.get_bind()
    schema = bind.execute(text("SELECT current_schema()" )).scalar_one()
    if schema == "public":
        return

    op.drop_index("ix_visits_facility_id", table_name="visits")
    op.drop_column("visits", "facility_id")