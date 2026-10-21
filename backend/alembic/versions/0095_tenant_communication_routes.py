"""Add tenant-scoped communication channel routes and MSG91 support."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0095"
down_revision = "0094"
branch_labels = None
depends_on = None

_SCHEMA = "public"
_PROVIDER_TABLES = (
    "tenant_provider_connections",
    "tenant_provider_credential_versions",
    "tenant_provider_webhook_routes",
    "tenant_provider_audit_events",
)
_PROVIDER_CONSTRAINTS = {
    "tenant_provider_connections": "ck_provider_connections_provider",
    "tenant_provider_credential_versions": "ck_provider_credentials_provider",
    "tenant_provider_webhook_routes": "ck_provider_webhook_routes_provider",
    "tenant_provider_audit_events": "ck_provider_audit_events_provider",
}


def _is_tenant(bind) -> bool:
    return bind.execute(text("SELECT current_schema()")).scalar() != _SCHEMA


def _has_table(bind, table: str) -> bool:
    return sa.inspect(bind).has_table(table, schema=_SCHEMA)


def _replace_provider_constraint(table: str, providers: tuple[str, ...]) -> None:
    bind = op.get_bind()
    if not _has_table(bind, table):
        return
    name = _PROVIDER_CONSTRAINTS[table]
    existing = {item["name"] for item in sa.inspect(bind).get_check_constraints(table, schema=_SCHEMA)}
    if name in existing:
        op.drop_constraint(name, table, type_="check", schema=_SCHEMA)
    provider_values = ", ".join(f"'{provider}'" for provider in providers)
    op.create_check_constraint(
        name,
        table,
        f"provider IN ({provider_values})",
        schema=_SCHEMA,
    )


def upgrade() -> None:
    bind = op.get_bind()
    if _is_tenant(bind):
        return

    for table in _PROVIDER_TABLES:
        _replace_provider_constraint(table, ("twilio", "msg91", "razorpay", "cloudinary"))

    if not _has_table(bind, "tenant_communication_routes"):
        op.create_table(
            "tenant_communication_routes",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("channel", sa.String(32), nullable=False),
            sa.Column("provider", sa.String(64), nullable=False),
            sa.Column("environment", sa.String(32), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"], name="fk_tenant_communication_routes_tenant", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["tenant_id", "provider", "environment"],
                [
                    "public.tenant_provider_connections.tenant_id",
                    "public.tenant_provider_connections.provider",
                    "public.tenant_provider_connections.environment",
                ],
                name="fk_tenant_communication_routes_connection",
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint("tenant_id", "channel", name="uq_tenant_communication_routes_channel"),
            sa.CheckConstraint("channel IN ('SMS', 'WHATSAPP')", name="ck_tenant_communication_routes_channel"),
            schema=_SCHEMA,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _is_tenant(bind):
        return

    if _has_table(bind, "tenant_communication_routes"):
        op.drop_table("tenant_communication_routes", schema=_SCHEMA)

    for table in _PROVIDER_TABLES:
        if not _has_table(bind, table):
            continue
        count = bind.execute(text(f'SELECT COUNT(*) FROM "{_SCHEMA}"."{table}" WHERE provider = \'msg91\'')).scalar_one()
        if count:
            raise RuntimeError(f"Cannot downgrade while MSG91 records exist in {_SCHEMA}.{table}")
        _replace_provider_constraint(table, ("twilio", "razorpay", "cloudinary"))
