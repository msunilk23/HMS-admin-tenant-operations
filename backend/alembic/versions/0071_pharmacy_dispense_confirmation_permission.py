"""Add permission for confirmed pharmacy dispensing."""

import uuid

from alembic import op
from sqlalchemy import text

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() != "public":
        return
    bind.execute(text("""
        INSERT INTO public.permissions (id, code, name, is_active)
        VALUES (:id, :code, :name, true)
        ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, is_active = true
    """), {"id": str(uuid.uuid4()), "code": "PHARMACY_DISPENSE_CONFIRM", "name": "Confirm pharmacy dispensing"})
    for role in ("pharmacist", "hospital_admin"):
        bind.execute(text("""
            INSERT INTO public.role_permissions (role, permission_id)
            SELECT :role, id FROM public.permissions WHERE code = :code
            ON CONFLICT (role, permission_id) DO NOTHING
        """), {"role": role, "code": "PHARMACY_DISPENSE_CONFIRM"})


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() != "public":
        return
    bind.execute(text("DELETE FROM public.role_permissions WHERE permission_id IN (SELECT id FROM public.permissions WHERE code = 'PHARMACY_DISPENSE_CONFIRM')"))
    bind.execute(text("DELETE FROM public.permissions WHERE code = 'PHARMACY_DISPENSE_CONFIRM'"))