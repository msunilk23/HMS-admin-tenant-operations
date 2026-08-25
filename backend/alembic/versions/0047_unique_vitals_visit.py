"""Enforce one vitals record per visit."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0047_unique_vitals_visit"
down_revision = "0046_schedule_audit_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    # Preserve the newest row if a legacy database contains duplicate drafts.
    op.execute(text("""
        DELETE FROM vitals older
        USING vitals newer
        WHERE older.visit_id = newer.visit_id
          AND older.recorded_at < newer.recorded_at
    """))
    inspector = sa.inspect(bind)
    constraints = {item["name"] for item in inspector.get_unique_constraints("vitals")}
    if "uq_vitals_visit_id" not in constraints:
        op.create_unique_constraint("uq_vitals_visit_id", "vitals", ["visit_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    op.drop_constraint("uq_vitals_visit_id", "vitals", type_="unique")
