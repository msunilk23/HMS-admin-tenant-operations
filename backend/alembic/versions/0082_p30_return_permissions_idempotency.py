"""Add P30 return permissions and patient return idempotency."""

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("PHARMACY_RETURN_REQUEST", "Request patient return", ("pharmacist", "hospital_admin")),
    ("PHARMACY_RETURN_VALIDATE", "Validate patient return", ("pharmacist", "hospital_admin")),
    ("PHARMACY_RETURN_ACCEPT", "Accept patient return", ("pharmacist", "hospital_admin")),
    ("PHARMACY_RETURN_REJECT", "Reject patient return", ("pharmacist", "hospital_admin")),
    ("SUPPLIER_RETURN_REQUEST", "Request supplier return", ("pharmacist", "hospital_admin")),
    ("SUPPLIER_RETURN_APPROVE", "Approve supplier return", ("pharmacist", "hospital_admin")),
    ("SUPPLIER_RETURN_DISPATCH", "Dispatch supplier return", ("pharmacist", "hospital_admin")),
    ("SUPPLIER_RETURN_RECEIVE", "Receive supplier return", ("pharmacist", "hospital_admin")),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
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
        return

    inspector = sa.inspect(bind)
    if inspector.has_table("patient_returns"):
        columns = {column["name"] for column in inspector.get_columns("patient_returns")}
        if "idempotency_key" not in columns:
            op.add_column("patient_returns", sa.Column("idempotency_key", sa.String(100), nullable=True))
        names = {item.get("name") for item in sa.inspect(bind).get_unique_constraints("patient_returns")}
        if "uq_patient_returns_tenant_idempotency" not in names:
            op.create_unique_constraint(
                "uq_patient_returns_tenant_idempotency",
                "patient_returns",
                ["tenant_id", "idempotency_key"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        codes = [permission[0] for permission in _PERMISSIONS]
        bind.execute(text("DELETE FROM public.role_permissions WHERE permission_id IN (SELECT id FROM public.permissions WHERE code = ANY(:codes))"), {"codes": codes})
        bind.execute(text("DELETE FROM public.permissions WHERE code = ANY(:codes)"), {"codes": codes})
        return
    inspector = sa.inspect(bind)
    if inspector.has_table("patient_returns"):
        names = {item.get("name") for item in inspector.get_unique_constraints("patient_returns")}
        if "uq_patient_returns_tenant_idempotency" in names:
            op.drop_constraint("uq_patient_returns_tenant_idempotency", "patient_returns", type_="unique")
        if "idempotency_key" in {column["name"] for column in inspector.get_columns("patient_returns")}:
            op.drop_column("patient_returns", "idempotency_key")