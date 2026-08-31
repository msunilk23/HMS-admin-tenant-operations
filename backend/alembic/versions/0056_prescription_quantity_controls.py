"""Add prescription quantity calculation and override fields."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("auto_quantity", sa.String(50)),
    ("final_quantity", sa.String(50)),
    ("quantity_override_flag", sa.Boolean(), sa.text("false")),
    ("quantity_override_reason", sa.Text()),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table("prescription_items"):
        return
    columns = {column["name"] for column in inspector.get_columns("prescription_items")}
    for entry in _COLUMNS:
        name, column_type, *server_default = entry
        if name not in columns:
            kwargs = {"nullable": False} if name == "quantity_override_flag" else {"nullable": True}
            if server_default:
                kwargs["server_default"] = server_default[0]
            op.add_column("prescription_items", sa.Column(name, column_type, **kwargs))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table("prescription_items"):
        return
    columns = {column["name"] for column in inspector.get_columns("prescription_items")}
    for entry in reversed(_COLUMNS):
        name = entry[0]
        if name in columns:
            op.drop_column("prescription_items", name)