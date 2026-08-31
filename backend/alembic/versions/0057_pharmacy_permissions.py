"""Add live pharmacy master permissions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
import uuid

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("PHARMACY_MASTER_VIEW", "View pharmacy master data"),
    ("PHARMACY_MASTER_CREATE", "Create pharmacy master data"),
    ("PHARMACY_MASTER_EDIT", "Edit pharmacy master data"),
    ("PHARMACY_FORMULARY_MANAGE", "Manage hospital formulary"),
)
_VIEW_ROLES = ("doctor", "pharmacist", "hospital_admin")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() != "public":
        return

    inspector = sa.inspect(bind)
    if not inspector.has_table("permissions", schema="public"):
        op.create_table(
            "permissions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("code", sa.String(100), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code"),
            schema="public",
        )
        op.create_index("ix_permissions_code", "permissions", ["code"], schema="public")

    if not inspector.has_table("role_permissions", schema="public"):
        op.create_table(
            "role_permissions",
            sa.Column("role", sa.String(50), nullable=False),
            sa.Column("permission_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.ForeignKeyConstraint(["permission_id"], ["public.permissions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("role", "permission_id"),
            sa.UniqueConstraint("role", "permission_id", name="uq_role_permissions_role_permission"),
            schema="public",
        )

    for code, name in _PERMISSIONS:
        bind.execute(
            text("""
                INSERT INTO public.permissions (id, code, name, is_active)
                VALUES (:id, :code, :name, true)
                ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, is_active = true
            """),
            {"id": str(uuid.uuid4()), "code": code, "name": name},
        )
        roles = _VIEW_ROLES if code == "PHARMACY_MASTER_VIEW" else ("hospital_admin",)
        for role in roles:
            bind.execute(
                text("""
                    INSERT INTO public.role_permissions (role, permission_id)
                    SELECT :role, id FROM public.permissions WHERE code = :code
                    ON CONFLICT (role, permission_id) DO NOTHING
                """),
                {"role": role, "code": code},
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() != "public":
        return
    bind.execute(text("""
        DELETE FROM public.role_permissions
        WHERE role = 'hospital_admin'
          AND permission_id IN (SELECT id FROM public.permissions WHERE code LIKE 'PHARMACY_%')
    """))
    bind.execute(text("DELETE FROM public.permissions WHERE code LIKE 'PHARMACY_%'"))
    if sa.inspect(bind).has_table("role_permissions", schema="public"):
        op.drop_table("role_permissions", schema="public")
    if sa.inspect(bind).has_table("permissions", schema="public"):
        op.drop_index("ix_permissions_code", table_name="permissions", schema="public")
        op.drop_table("permissions", schema="public")
