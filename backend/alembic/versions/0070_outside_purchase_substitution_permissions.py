"""Add P28 outside-purchase and substitution permissions."""

import uuid

from alembic import op
from sqlalchemy import text

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("PHARMACY_DISPENSE_OUTSIDE_PURCHASE", "Record pharmacy outside purchase", ("pharmacist", "hospital_admin")),
    ("PHARMACY_DISPENSE_SUBSTITUTE", "Approve pharmacy substitution", ("pharmacist", "hospital_admin")),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() != "public":
        return
    for code, name, roles in _PERMISSIONS:
        bind.execute(
            text("""
                INSERT INTO public.permissions (id, code, name, is_active)
                VALUES (:id, :code, :name, true)
                ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, is_active = true
            """),
            {"id": str(uuid.uuid4()), "code": code, "name": name},
        )
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
    codes = [permission[0] for permission in _PERMISSIONS]
    bind.execute(text("DELETE FROM public.role_permissions WHERE permission_id IN (SELECT id FROM public.permissions WHERE code = ANY(:codes))"), {"codes": codes})
    bind.execute(text("DELETE FROM public.permissions WHERE code = ANY(:codes)"), {"codes": codes})