"""Add permission for controlled pharmacy stock adjustments."""

import uuid

from alembic import op
from sqlalchemy import text

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() != "public":
        return
    bind.execute(
        text("""
            INSERT INTO public.permissions (id, code, name, is_active)
            VALUES (:id, :code, :name, true)
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, is_active = true
        """),
        {"id": str(uuid.uuid4()), "code": "PHARMACY_STOCK_ADJUST", "name": "Adjust pharmacy stock"},
    )
    for role in ("store_manager", "hospital_admin"):
        bind.execute(
            text("""
                INSERT INTO public.role_permissions (role, permission_id)
                SELECT :role, id FROM public.permissions WHERE code = :code
                ON CONFLICT (role, permission_id) DO NOTHING
            """),
            {"role": role, "code": "PHARMACY_STOCK_ADJUST"},
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() != "public":
        return
    bind.execute(
        text("DELETE FROM public.role_permissions WHERE permission_id IN (SELECT id FROM public.permissions WHERE code = 'PHARMACY_STOCK_ADJUST')")
    )
    bind.execute(text("DELETE FROM public.permissions WHERE code = 'PHARMACY_STOCK_ADJUST'"))