"""Make visits.doctor_id nullable to support walk-in check-ins without a pre-assigned doctor."""

from alembic import op
from sqlalchemy import text

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    op.alter_column("visits", "doctor_id", nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    # NOTE: will fail if any visits have doctor_id = NULL
    op.alter_column("visits", "doctor_id", nullable=False)
