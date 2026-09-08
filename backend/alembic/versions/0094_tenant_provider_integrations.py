"""Add tenant-scoped provider integrations and encrypted secret storage metadata.

This migration is intentionally contract-driven and additive. It supports fresh
install, upgrade from 0093, replay of a compatible schema, and downgrade back to 0093.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0094"
down_revision = "0093"
branch_labels = None
depends_on = None

_MARKER = "hms_0094_provider_integrations"
_SCHEMA = "public"


def _is_tenant(bind) -> bool:
    return bind.execute(text("SELECT current_schema()" )).scalar() != "public"


def _inspect(bind):
    return sa.inspect(bind)


def _has_table(bind, table: str) -> bool:
    return _inspect(bind).has_table(table, schema=_SCHEMA)


def _columns(bind, table: str) -> dict:
    return {item["name"]: item for item in _inspect(bind).get_columns(table, schema=_SCHEMA)}


def _indexes(bind, table: str) -> list[dict]:
    return _inspect(bind).get_indexes(table, schema=_SCHEMA)


def _unique_constraints(bind, table: str) -> list[dict]:
    return _inspect(bind).get_unique_constraints(table, schema=_SCHEMA)


def _checks(bind, table: str) -> list[dict]:
    return _inspect(bind).get_check_constraints(table)


def _foreign_keys(bind, table: str) -> list[dict]:
    return _inspect(bind).get_foreign_keys(table)


def _count(bind, table: str) -> int:
    return int(bind.execute(text(f'SELECT COUNT(*) FROM "public"."{table}"')).scalar_one())


def _expected_type(value):
    t = value.type if isinstance(value, sa.Column) else value

    if isinstance(t, (postgresql.UUID, sa.Uuid)):
        return ("uuid", None)
    if isinstance(t, postgresql.JSONB):
        return ("jsonb", None)
    if isinstance(t, sa.Text):
        return ("text", None)
    if isinstance(t, sa.String):
        return ("varchar", t.length)
    if isinstance(t, sa.Integer):
        return ("integer", None)
    if isinstance(t, sa.Boolean):
        return ("boolean", None)
    if isinstance(t, sa.DateTime):
        return ("timestamptz" if t.timezone else "timestamp", None)
    return (t.__class__.__name__.lower(), getattr(t, "length", None))


def _compatible_column(bind, table: str, expected: sa.Column) -> None:
    actual = _columns(bind, table).get(expected.name)
    if actual is None:
        existing_rows = _count(bind, table)
        if not expected.nullable and expected.server_default is None and existing_rows:
            raise RuntimeError(f"0094 incompatible {table}.{expected.name}: required column missing on non-empty table")
        op.add_column(table, expected.copy(), schema=_SCHEMA)
        return
    if _expected_type(actual["type"]) != _expected_type(expected):
        raise RuntimeError(f"0094 incompatible {table}.{expected.name}: expected {_expected_type(expected)}, found {_expected_type(actual['type'])}")
    if expected.nullable is False and actual["nullable"]:
        nulls = bind.execute(text(f'SELECT COUNT(*) FROM "public"."{table}" WHERE "{expected.name}" IS NULL')).scalar_one()
        if nulls:
            raise RuntimeError(f"0094 incompatible {table}.{expected.name}: NULL values violate NOT NULL")
        op.alter_column(table, expected.name, nullable=False, schema=_SCHEMA)


def _ensure_unique(bind, table: str, name: str, columns: list[str]) -> None:
    existing = next((item for item in _unique_constraints(bind, table) if item.get("name") == name), None)
    if existing is not None:
        if existing.get("column_names") != columns:
            raise RuntimeError(f"0094 incompatible unique constraint {table}.{name}: expected {columns}, found {existing.get('column_names')}")
        return
    for index in _indexes(bind, table):
        if index.get("name") == name and index.get("unique") and index.get("column_names") == columns:
            return
    if any(item.get("column_names") == columns and item.get("unique") for item in _indexes(bind, table)):
        return
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    duplicates = bind.execute(text(f'SELECT COUNT(*) FROM (SELECT {quoted_columns}, COUNT(*) FROM "public"."{table}" GROUP BY {quoted_columns} HAVING COUNT(*) > 1) d')).scalar_one()
    if duplicates:
        raise RuntimeError(f"0094 data violates unique contract {table}.{name}")
    op.create_unique_constraint(name, table, columns, schema=_SCHEMA)


def upgrade() -> None:
    bind = op.get_bind()

    # 0094 objects are public-scoped. Tenant invocations only advance their
    # own Alembic version table.
    if _is_tenant(bind):
        return

    public_tables = [
        "tenant_provider_connections",
        "tenant_provider_credential_versions",
        "tenant_provider_webhook_routes",
        "tenant_provider_audit_events",
    ]
    for table in public_tables:
        if not _has_table(bind, table):
            if table == "tenant_provider_connections":
                op.create_table(
                    table,
                    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
                    sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
                    sa.Column("provider", sa.String(64), nullable=False),
                    sa.Column("capability", sa.String(64), nullable=False),
                    sa.Column("environment", sa.String(32), nullable=False),
                    sa.Column("status", sa.String(32), nullable=False, server_default="DISABLED"),
                    sa.Column("connection_tested_at", sa.DateTime(timezone=True), nullable=True),
                    sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
                    sa.Column("last_error", sa.Text(), nullable=True),
                    sa.Column("credential_version", sa.Integer(), nullable=False, server_default="1"),
                    sa.Column("connection_name", sa.String(128), nullable=True),
                    sa.Column("public_configuration", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
                    sa.Column("endpoint_id", sa.String(80), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
                    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
                    sa.Column("created_by", sa.String(128), nullable=True),
                    sa.Column("updated_by", sa.String(128), nullable=True),
                    sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"], name="fk_provider_connections_tenant_id", ondelete="CASCADE"),
                    sa.CheckConstraint("status IN ('DISABLED','TEST','LIVE')", name="ck_provider_connections_status"),
                    sa.CheckConstraint("credential_version > 0", name="ck_provider_connections_credential_version"),
                    sa.UniqueConstraint("tenant_id", "provider", "environment", name="uq_provider_connections_tenant_provider_env"),
                    sa.UniqueConstraint("endpoint_id", name="uq_provider_connections_endpoint_id"),
                    schema="public",
                )
            elif table == "tenant_provider_credential_versions":
                op.create_table(
                    table,
                    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
                    sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
                    sa.Column("provider", sa.String(64), nullable=False),
                    sa.Column("capability", sa.String(64), nullable=False),
                    sa.Column("environment", sa.String(32), nullable=False),
                    sa.Column("credential_version", sa.Integer(), nullable=False),
                    sa.Column("secret_ciphertext", sa.Text(), nullable=False),
                    sa.Column("secret_nonce", sa.String(128), nullable=False),
                    sa.Column("key_version", sa.String(64), nullable=False),
                    sa.Column("algorithm", sa.String(32), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
                    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
                    sa.Column("versioned_by", sa.String(128), nullable=True),
                    sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"], name="fk_provider_credential_versions_tenant_id", ondelete="CASCADE"),
                    sa.CheckConstraint("credential_version > 0", name="ck_provider_credential_versions_version"),
                    sa.UniqueConstraint("tenant_id", "provider", "environment", "credential_version", name="uq_provider_credentials_tenant_provider_env_version"),
                    schema="public",
                )
            elif table == "tenant_provider_webhook_routes":
                op.create_table(
                    table,
                    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
                    sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
                    sa.Column("provider", sa.String(64), nullable=False),
                    sa.Column("capability", sa.String(64), nullable=False),
                    sa.Column("environment", sa.String(32), nullable=False),
                    sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
                    sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
                    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
                    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
                    sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"], name="fk_provider_webhook_routes_tenant_id", ondelete="CASCADE"),
                    sa.ForeignKeyConstraint(["connection_id"], ["public.tenant_provider_connections.id"], name="fk_provider_webhook_routes_connection_id", ondelete="CASCADE"),
                    sa.UniqueConstraint("connection_id", name="uq_provider_webhook_routes_connection_id"),
                    schema="public",
                )
            elif table == "tenant_provider_audit_events":
                op.create_table(
                    table,
                    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
                    sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
                    sa.Column("provider", sa.String(64), nullable=False),
                    sa.Column("capability", sa.String(64), nullable=False),
                    sa.Column("environment", sa.String(32), nullable=False),
                    sa.Column("event_type", sa.String(64), nullable=False),
                    sa.Column("event_metadata", postgresql.JSONB(), nullable=True),
                    sa.Column("result", sa.String(32), nullable=True),
                    sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
                    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
                    sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"], name="fk_provider_audit_events_tenant_id", ondelete="CASCADE"),
                    schema="public",
                )

    # Ensure the public schema tables that exist are compatible with the contract.
    if _has_table(bind, "tenant_provider_connections"):
        conn_cols = _columns(bind, "tenant_provider_connections")
        required = {
            "id": sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            "tenant_id": sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            "provider": sa.Column("provider", sa.String(64), nullable=False),
            "capability": sa.Column("capability", sa.String(64), nullable=False),
            "environment": sa.Column("environment", sa.String(32), nullable=False),
            "status": sa.Column("status", sa.String(32), nullable=False, server_default="DISABLED"),
            "credential_version": sa.Column("credential_version", sa.Integer(), nullable=False, server_default="1"),
            "connection_name": sa.Column("connection_name", sa.String(128), nullable=True),
            "public_configuration": sa.Column("public_configuration", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            "endpoint_id": sa.Column("endpoint_id", sa.String(80), nullable=False),
            "created_at": sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            "updated_at": sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        }
        for name, column in required.items():
            _compatible_column(bind, "tenant_provider_connections", column)
        _ensure_unique(bind, "tenant_provider_connections", "uq_provider_connections_tenant_provider_env", ["tenant_id", "provider", "environment"])
        _ensure_unique(bind, "tenant_provider_connections", "uq_provider_connections_endpoint_id", ["endpoint_id"])

    if _has_table(bind, "tenant_provider_credential_versions"):
        conn_cols = _columns(bind, "tenant_provider_credential_versions")
        required = {
            "id": sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            "tenant_id": sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            "provider": sa.Column("provider", sa.String(64), nullable=False),
            "capability": sa.Column("capability", sa.String(64), nullable=False),
            "environment": sa.Column("environment", sa.String(32), nullable=False),
            "credential_version": sa.Column("credential_version", sa.Integer(), nullable=False),
            "secret_ciphertext": sa.Column("secret_ciphertext", sa.Text(), nullable=False),
            "secret_nonce": sa.Column("secret_nonce", sa.String(128), nullable=False),
            "key_version": sa.Column("key_version", sa.String(64), nullable=False),
            "algorithm": sa.Column("algorithm", sa.String(32), nullable=False),
            "created_at": sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            "updated_at": sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        }
        for name, column in required.items():
            _compatible_column(bind, "tenant_provider_credential_versions", column)
        _ensure_unique(bind, "tenant_provider_credential_versions", "uq_provider_credentials_tenant_provider_env_version", ["tenant_id", "provider", "environment", "credential_version"])

    if _has_table(bind, "tenant_provider_audit_events"):
        required = {
            "id": sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            "tenant_id": sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            "provider": sa.Column("provider", sa.String(64), nullable=False),
            "capability": sa.Column("capability", sa.String(64), nullable=False),
            "environment": sa.Column("environment", sa.String(32), nullable=False),
            "event_type": sa.Column("event_type", sa.String(64), nullable=False),
            "created_at": sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        }
        for name, column in required.items():
            _compatible_column(bind, "tenant_provider_audit_events", column)


def downgrade() -> None:
    bind = op.get_bind()
    if _is_tenant(bind):
        return
    for table in ["tenant_provider_audit_events", "tenant_provider_webhook_routes", "tenant_provider_credential_versions", "tenant_provider_connections"]:
        if _has_table(bind, table):
            op.drop_table(table, schema=_SCHEMA)
