"""Add tenant-scoped clinical alerts for longitudinal warnings."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.create_table(
        "clinical_alerts",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", sa.UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("alert_type", sa.String(30), nullable=False, server_default="allergy"),
        sa.Column("severity", sa.String(20), nullable=False, server_default="critical"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_user_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("resolved_by_user_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_clinical_alerts_patient_id", "clinical_alerts", ["patient_id"])
    op.create_index("ix_clinical_alerts_is_active", "clinical_alerts", ["is_active"])


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return
    op.drop_index("ix_clinical_alerts_is_active", table_name="clinical_alerts")
    op.drop_index("ix_clinical_alerts_patient_id", table_name="clinical_alerts")
    op.drop_table("clinical_alerts")
