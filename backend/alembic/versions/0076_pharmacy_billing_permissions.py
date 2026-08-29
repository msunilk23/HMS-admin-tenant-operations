"""Add granular P29.10 Pharmacy billing permissions."""

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("PHARMACY_BILLING_VIEW", "View Pharmacy billing state", ("pharmacist", "billing_officer", "hospital_admin")),
    ("PHARMACY_BILLING_CREATE", "Create Pharmacy invoice", ("pharmacist", "hospital_admin")),
    ("PHARMACY_BILLING_PAYMENT", "Initiate Pharmacy payment", ("pharmacist", "billing_officer", "hospital_admin")),
    ("PHARMACY_BILLING_VERIFY", "Verify Pharmacy online payment", ("pharmacist", "billing_officer", "hospital_admin")),
    ("PHARMACY_BILLING_CANCEL", "Cancel unpaid Pharmacy billing", ("pharmacist", "billing_officer", "hospital_admin")),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() != "public":
        inspector = sa.inspect(bind)
        if inspector.has_table("audit_logs"):
            op.alter_column("audit_logs", "action", type_=sa.String(64), existing_type=sa.String(20), existing_nullable=False)
        return
    for code, name, roles in _PERMISSIONS:
        bind.execute(text("""
            INSERT INTO public.permissions (id, code, name, is_active)
            VALUES (:id, :code, :name, true)
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, is_active = true
        """), {"id": str(uuid.uuid4()), "code": code, "name": name})
        for role in roles:
            bind.execute(text("""
                INSERT INTO public.role_permissions (role, permission_id)
                SELECT :role, id FROM public.permissions WHERE code = :code
                ON CONFLICT (role, permission_id) DO NOTHING
            """), {"role": role, "code": code})


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() != "public":
        inspector = sa.inspect(bind)
        if inspector.has_table("audit_logs"):
            op.alter_column("audit_logs", "action", type_=sa.String(20), existing_type=sa.String(64), existing_nullable=False)
        return
    codes = [permission[0] for permission in _PERMISSIONS]
    bind.execute(text("""
        DELETE FROM public.role_permissions
        WHERE permission_id IN (SELECT id FROM public.permissions WHERE code = ANY(:codes))
    """), {"codes": codes})
    bind.execute(text("DELETE FROM public.permissions WHERE code = ANY(:codes)"), {"codes": codes})
