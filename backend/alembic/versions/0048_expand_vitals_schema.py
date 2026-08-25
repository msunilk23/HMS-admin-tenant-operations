"""Add expanded clinical vitals columns to existing tenant schemas."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0048_expand_vitals_schema"
down_revision = "0047_unique_vitals_visit"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("respiratory_rate", "INTEGER"),
    ("pain_score", "INTEGER"),
    ("bmi", "DOUBLE PRECISION"),
    ("blood_glucose", "DOUBLE PRECISION"),
    ("chief_complaint", "TEXT"),
    ("allergies", "TEXT"),
    ("known_no_allergies", "BOOLEAN"),
    ("general_condition", "VARCHAR(100)"),
    ("level_of_consciousness", "VARCHAR(100)"),
    ("nurse_notes", "TEXT"),
    ("status", "VARCHAR(20) NOT NULL DEFAULT 'draft'"),
    ("started_at", "TIMESTAMPTZ"),
    ("completed_at", "TIMESTAMPTZ"),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return

    inspector = sa.inspect(bind)
    if not inspector.has_table("vitals"):
        return

    columns = {column["name"] for column in inspector.get_columns("vitals")}
    for name, definition in _COLUMNS:
        if name not in columns:
            op.execute(text(f'ALTER TABLE "vitals" ADD COLUMN "{name}" {definition}'))

    # uhid was introduced by 0009, but preserve compatibility with a partially
    # upgraded tenant that somehow lacks it. The value is nullable here so no
    # clinical data is fabricated and legacy rows remain migratable.
    if "uhid" not in columns:
        op.add_column("vitals", sa.Column("uhid", sa.String(20), nullable=True))

    op.execute(text("UPDATE vitals SET started_at = recorded_at WHERE started_at IS NULL"))
    op.execute(text("""
        UPDATE vitals v
        SET uhid = p.uhid
        FROM visits vi
        JOIN patients p ON p.id = vi.patient_id
        WHERE v.visit_id = vi.id AND v.uhid IS NULL
    """))
    op.execute(text("""
        UPDATE vitals v
        SET status = 'completed', completed_at = COALESCE(v.completed_at, v.recorded_at)
        FROM visits vi
        WHERE v.visit_id = vi.id
          AND COALESCE(vi.status, '') IN (
              'WAITING_FOR_DOCTOR', 'IN_CONSULTATION',
              'CONSULTATION_COMPLETED', 'CLOSED'
          )
          AND v.status = 'draft'
    """))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("vitals")}
    for name, _ in reversed(_COLUMNS):
        if name in columns:
            op.drop_column("vitals", name)
    # Do not drop uhid: it belongs to the earlier 0009 contract.
