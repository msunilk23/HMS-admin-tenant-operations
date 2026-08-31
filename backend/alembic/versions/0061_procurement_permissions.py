"""Add procurement permissions for supplier, PO, and GRN operations."""

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("PHARMACY_SUPPLIER_VIEW", "View pharmacy suppliers", ("pharmacist", "store_manager", "hospital_admin")),
    ("PHARMACY_SUPPLIER_MANAGE", "Manage pharmacy suppliers", ("store_manager", "hospital_admin")),
    ("PHARMACY_PO_VIEW", "View pharmacy purchase orders", ("pharmacist", "store_manager", "hospital_admin")),
    ("PHARMACY_PO_CREATE", "Create pharmacy purchase orders", ("store_manager", "hospital_admin")),
    ("PHARMACY_PO_EDIT", "Edit draft pharmacy purchase orders", ("store_manager", "hospital_admin")),
    ("PHARMACY_PO_SUBMIT", "Submit pharmacy purchase orders", ("store_manager", "hospital_admin")),
    ("PHARMACY_PO_APPROVE", "Approve pharmacy purchase orders", ("hospital_admin",)),
    ("PHARMACY_PO_SEND", "Send pharmacy purchase orders", ("store_manager", "hospital_admin")),
    ("PHARMACY_PO_CANCEL", "Cancel pharmacy purchase orders", ("store_manager", "hospital_admin")),
    ("PHARMACY_GRN_VIEW", "View pharmacy goods receipts", ("pharmacist", "store_manager", "hospital_admin")),
    ("PHARMACY_GRN_CREATE", "Create pharmacy goods receipts", ("store_manager", "hospital_admin")),
    ("PHARMACY_GRN_RECEIVE", "Receive pharmacy goods", ("store_manager", "hospital_admin")),
    ("PHARMACY_GRN_FINALIZE", "Finalize pharmacy goods receipts", ("store_manager", "hospital_admin")),
    ("PHARMACY_GRN_CANCEL", "Cancel pharmacy goods receipts", ("hospital_admin",)),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() != "public":
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table("permissions", schema="public") or not inspector.has_table("role_permissions", schema="public"):
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
    codes = tuple(permission[0] for permission in _PERMISSIONS)
    bind.execute(
        text("DELETE FROM public.role_permissions WHERE permission_id IN (SELECT id FROM public.permissions WHERE code = ANY(:codes))"),
        {"codes": list(codes)},
    )
    bind.execute(
        text("DELETE FROM public.permissions WHERE code = ANY(:codes)"),
        {"codes": list(codes)},
    )
