"""Decouple platform Super Admin users from tenant lifecycle.

Revision ID: 0089
Revises: 0088
"""
from alembic import op
import sqlalchemy as sa


revision = "0089"
down_revision = "0088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    schema = op.get_context().version_table_schema
    if schema != "public":
        return

    op.alter_column("users", "tenant_id", schema="public", nullable=True)
    op.alter_column("users", "tenant_name", schema="public", nullable=True)
    op.drop_constraint("users_tenant_id_fkey", "users", schema="public", type_="foreignkey")
    op.create_foreign_key(
        "users_tenant_id_fkey",
        "users",
        "tenants",
        ["tenant_id"],
        ["id"],
        source_schema="public",
        referent_schema="public",
        ondelete="SET NULL",
    )
    op.execute(
        sa.text(
            "UPDATE public.users "
            "SET tenant_id = NULL, tenant_name = NULL "
            "WHERE role = 'super_admin'"
        )
    )


def downgrade() -> None:
    schema = op.get_context().version_table_schema
    if schema != "public":
        return

    orphaned = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM public.users "
            "WHERE tenant_id IS NULL OR tenant_name IS NULL"
        )
    ).scalar_one()
    if orphaned:
        raise RuntimeError(
            "Cannot downgrade while tenant-independent users exist; assign them to a tenant first"
        )

    op.drop_constraint("users_tenant_id_fkey", "users", schema="public", type_="foreignkey")
    op.create_foreign_key(
        "users_tenant_id_fkey",
        "users",
        "tenants",
        ["tenant_id"],
        ["id"],
        source_schema="public",
        referent_schema="public",
    )
    op.alter_column("users", "tenant_name", schema="public", nullable=False)
    op.alter_column("users", "tenant_id", schema="public", nullable=False)