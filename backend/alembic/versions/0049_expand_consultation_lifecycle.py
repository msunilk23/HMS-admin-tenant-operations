"""Add consultation lifecycle columns to tenant schemas."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0049_consultation_lifecycle"
down_revision = "0048_expand_vitals_schema"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("status", "VARCHAR(20) NOT NULL DEFAULT 'draft'"),
    ("started_at", "TIMESTAMPTZ"),
    ("completed_at", "TIMESTAMPTZ"),
    ("amended_at", "TIMESTAMPTZ"),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table("consultations"):
        return

    columns = {column["name"] for column in inspector.get_columns("consultations")}
    for name, definition in _COLUMNS:
        if name not in columns:
            op.execute(text(f'ALTER TABLE "consultations" ADD COLUMN "{name}" {definition}'))

    op.execute(text("UPDATE consultations SET started_at = created_at WHERE started_at IS NULL"))
    op.execute(text("""
        UPDATE consultations c
        SET status = CASE
                WHEN v.status IN ('CONSULTATION_COMPLETED', 'CLOSED') THEN 'completed'
                WHEN v.status = 'IN_CONSULTATION' THEN 'in_progress'
                ELSE 'draft'
            END,
            completed_at = CASE
                WHEN v.status IN ('CONSULTATION_COMPLETED', 'CLOSED') THEN c.created_at
                ELSE NULL
            END
        FROM visits v
        WHERE c.visit_id = v.id
          AND c.status = 'draft'
    """))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table("consultations"):
        return
    columns = {column["name"] for column in inspector.get_columns("consultations")}
    for name, _ in reversed(_COLUMNS):
        if name in columns:
            op.drop_column("consultations", name)
