"""Create and harden the PF-1 post-consultation routing schema.

This migration is intentionally contract-driven. Existing compatible partial
schemas are completed; incompatible definitions or data fail explicitly.
"""
from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0093"
down_revision = "0092"
branch_labels = None
depends_on = None

_MARKER = "hms_0093_owned"


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _jsonb():
    return postgresql.JSONB()


def _is_tenant(bind) -> bool:
    return bind.execute(sa.text("SELECT current_schema()")).scalar() != "public"


def _inspector(bind):
    return sa.inspect(bind)


def _has_table(bind, table: str) -> bool:
    return _inspector(bind).has_table(table)


def _columns(bind, table: str) -> dict:
    return {item["name"]: item for item in _inspector(bind).get_columns(table)}


def _indexes(bind, table: str) -> list[dict]:
    return _inspector(bind).get_indexes(table)


def _unique_constraints(bind, table: str) -> list[dict]:
    return _inspector(bind).get_unique_constraints(table)


def _checks(bind, table: str) -> list[dict]:
    return _inspector(bind).get_check_constraints(table)


def _foreign_keys(bind, table: str) -> list[dict]:
    return _inspector(bind).get_foreign_keys(table)


def _index_predicate(bind, index_name: str) -> str:
    value = bind.execute(sa.text("""
        SELECT pg_get_expr(i.indpred, i.indrelid)
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = :index_name AND n.nspname = current_schema()
    """), {"index_name": index_name}).scalar()
    return "".join(str(value or "").lower().replace('"', "").replace("(", "").replace(")", "").split())


def _pk_columns(bind, table: str) -> list[str]:
    return _inspector(bind).get_pk_constraint(table).get("constrained_columns") or []


def _count(bind, table: str) -> int:
    return int(bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one())


def _type_signature(column_type) -> tuple[str, int | None]:
    name = column_type.__class__.__name__.lower()
    length = getattr(column_type, "length", None)
    if isinstance(column_type, postgresql.UUID):
        return ("uuid", None)
    if isinstance(column_type, postgresql.JSONB):
        return ("jsonb", None)
    if isinstance(column_type, sa.DateTime):
        return ("timestamptz" if column_type.timezone else "timestamp", None)
    if isinstance(column_type, sa.Integer):
        return ("integer", None)
    if isinstance(column_type, sa.Boolean):
        return ("boolean", None)
    if isinstance(column_type, sa.Text):
        return ("text", None)
    if isinstance(column_type, sa.String):
        return ("varchar", length)
    return (name, length)


def _expected_type(column: sa.Column) -> tuple[str, int | None]:
    return _type_signature(column.type)


def _column_comment(bind, table: str, column: str) -> str | None:
    return bind.execute(sa.text("SELECT col_description(:oid, :attnum)"), {
        "oid": f'"{table}"' ,
        "attnum": 0,
    }).scalar()


def _mark_table(bind, table: str) -> None:
    bind.execute(sa.text(f"COMMENT ON TABLE \"{table}\" IS '{_MARKER}'"))


def _table_owned(bind, table: str) -> bool:
    return bind.execute(sa.text("SELECT obj_description(to_regclass(:table), 'pg_class')"), {"table": table}).scalar() == _MARKER


def _mark_column(bind, table: str, column: str) -> None:
    bind.execute(sa.text(f"COMMENT ON COLUMN \"{table}\".\"{column}\" IS '{_MARKER}'"))


def _column_owned(bind, table: str, column: str) -> bool:
    return bind.execute(sa.text("SELECT col_description(to_regclass(:table), :attnum)"), {"table": table, "attnum": 0}).scalar() == _MARKER


def _compatible_column(bind, table: str, expected: sa.Column) -> None:
    actual = _columns(bind, table).get(expected.name)
    if actual is None:
        existing_rows = _count(bind, table)
        if not expected.nullable and expected.server_default is None and existing_rows:
            raise RuntimeError(f"0093 incompatible {table}.{expected.name}: required column missing on non-empty table")
        op.add_column(table, expected.copy())
        if not _table_owned(bind, table):
            _mark_column(bind, table, expected.name)
        return

    actual_type = _type_signature(actual["type"])
    expected_type = _expected_type(expected)
    if actual_type != expected_type:
        raise RuntimeError(f"0093 incompatible {table}.{expected.name}: expected {expected_type}, found {actual_type}")
    if expected.nullable is False and actual["nullable"]:
        nulls = bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table}" WHERE "{expected.name}" IS NULL')).scalar_one()
        if nulls:
            raise RuntimeError(f"0093 incompatible {table}.{expected.name}: {nulls} NULL values violate NOT NULL")
        op.alter_column(table, expected.name, nullable=False)
    elif expected.nullable is True and not actual["nullable"]:
        raise RuntimeError(f"0093 incompatible {table}.{expected.name}: existing NOT NULL is stricter than contract")
    expected_default = getattr(expected.server_default, "arg", None)
    if expected_default is not None and actual.get("default") is None:
        op.alter_column(table, expected.name, server_default=expected_default)


def _create_table_if_absent(bind, table: str, columns: list[sa.Column], constraints: tuple = ()) -> bool:
    if _has_table(bind, table):
        return False
    op.create_table(table, *[column.copy() for column in columns], *constraints)
    _mark_table(bind, table)
    return True


def _ensure_primary_key(bind, table: str, columns: list[str]) -> None:
    actual = _pk_columns(bind, table)
    if actual == columns:
        return
    if actual:
        raise RuntimeError(f"0093 incompatible {table} primary key: expected {columns}, found {actual}")
    if _count(bind, table):
        raise RuntimeError(f"0093 incompatible {table} primary key: existing rows prevent adding {columns}")
    op.create_primary_key(f"pk_{table}", table, columns)


def _ensure_foreign_key(bind, table: str, name: str, local: list[str], referred_table: str, referred: list[str], *, ondelete: str | None = None) -> None:
    for fk in _foreign_keys(bind, table):
        if fk.get("constrained_columns") == local and fk.get("referred_table") == referred_table and fk.get("referred_columns") == referred:
            return
    if name in {fk.get("name") for fk in _foreign_keys(bind, table)}:
        raise RuntimeError(f"0093 incompatible {table} foreign key {name}: definition differs")
    op.create_foreign_key(name, table, referred_table, local, referred, ondelete=ondelete)


def _ensure_unique(bind, table: str, name: str, columns: list[str]) -> None:
    named = next((item for item in _unique_constraints(bind, table) if item.get("name") == name), None)
    if named is not None:
        if named.get("column_names") != columns:
            raise RuntimeError(f"0093 incompatible unique constraint {table}.{name}: expected {columns}, found {named.get('column_names')}")
        return
    named_index = next((item for item in _indexes(bind, table) if item.get("name") == name), None)
    if named_index is not None:
        if named_index.get("column_names") != columns or not named_index.get("unique"):
            raise RuntimeError(f"0093 incompatible unique index {table}.{name}")
        return
    if any(item.get("column_names") == columns and item.get("unique") for item in _indexes(bind, table)):
        return
    duplicate = bind.execute(sa.text(f'SELECT COUNT(*) FROM (SELECT "{columns[0]}", COUNT(*) FROM "{table}" GROUP BY "{columns[0]}" HAVING COUNT(*) > 1) d')).scalar_one() if len(columns) == 1 else bind.execute(sa.text(f'SELECT COUNT(*) FROM (SELECT "{columns[0]}", "{columns[1]}", COUNT(*) FROM "{table}" GROUP BY "{columns[0]}", "{columns[1]}" HAVING COUNT(*) > 1) d')).scalar_one()
    if duplicate:
        raise RuntimeError(f"0093 data violates {table} unique contract {columns}: duplicate groups={duplicate}")
    op.create_unique_constraint(name, table, columns)


def _ensure_check(bind, table: str, name: str, expression: str, violation_sql: str) -> None:
    checks = _checks(bind, table)
    named = next((item for item in checks if item.get("name") == name), None)
    if named is not None:
        actual = "".join(str(named.get("sqltext", "")).lower().replace('"', "").split())
        wanted = "".join(expression.lower().replace('"', "").split())
        wanted_literals = set(re.findall(r"'([^']+)'", expression.lower()))
        actual_literals = set(re.findall(r"'([^']+)'", actual))
        equivalent = actual == wanted or (wanted_literals and wanted_literals == actual_literals)
        if not equivalent:
            raise RuntimeError(f"0093 incompatible check constraint {table}.{name}")
        return
    normalized = "".join("".join(str(item.get("sqltext", "")).lower().replace('"', "").split()) for item in checks)
    wanted = "".join(expression.lower().replace('"', "").split())
    if normalized and (wanted in normalized or normalized in wanted):
        return
    violation = bind.execute(sa.text(violation_sql)).scalar_one()
    if violation:
        raise RuntimeError(f"0093 data violates {table} check contract {name}: violations={violation}")
    op.create_check_constraint(name, table, expression)


def _ensure_index(bind, table: str, name: str, columns: list[str], *, unique: bool = False, where: str | None = None) -> None:
    existing = _indexes(bind, table)
    by_name = next((item for item in existing if item.get("name") == name), None)
    if by_name:
        existing_where = _index_predicate(bind, name)
        wanted_where = (where or "").replace(" ", "").replace("(", "").replace(")", "").lower()
        if by_name.get("column_names") != columns or bool(by_name.get("unique")) != unique or existing_where != wanted_where:
            raise RuntimeError(f"0093 incompatible index {table}.{name}")
        return
    for item in existing:
        if item.get("column_names") == columns and bool(item.get("unique")) == unique:
            existing_where = _index_predicate(bind, item["name"])
            wanted_where = (where or "").replace(" ", "").replace("(", "").replace(")", "").lower()
            if existing_where == wanted_where:
                return
    op.create_index(name, table, columns, unique=unique, postgresql_where=sa.text(where) if where else None)


def _upgrade_config(bind) -> None:
    columns = [sa.Column("id", _uuid(), primary_key=True), sa.Column("tenant_id", _uuid(), nullable=False), sa.Column("facility_id", _uuid()), sa.Column("presentation_window_minutes", sa.Integer(), nullable=False, server_default="30"), *[sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]]
    _create_table_if_absent(bind, "patient_route_configurations", columns)
    for column in columns:
        _compatible_column(bind, "patient_route_configurations", column)
    _ensure_primary_key(bind, "patient_route_configurations", ["id"])
    bad_window = bind.execute(sa.text('SELECT COUNT(*) FROM "patient_route_configurations" WHERE presentation_window_minutes <= 0')).scalar_one()
    if bad_window:
        raise RuntimeError(f"0093 data violates patient_route_configurations check contract ck_patient_route_config_positive_window: violations={bad_window}")
    _ensure_check(bind, "patient_route_configurations", "ck_patient_route_config_positive_window", "presentation_window_minutes > 0", 'SELECT COUNT(*) FROM "patient_route_configurations" WHERE presentation_window_minutes <= 0')
    _ensure_index(bind, "patient_route_configurations", "ix_patient_route_configurations_tenant_id", ["tenant_id"])
    _ensure_index(bind, "patient_route_configurations", "ix_patient_route_configurations_facility_id", ["facility_id"])
    _ensure_index(bind, "patient_route_configurations", "uq_patient_route_config_tenant_default", ["tenant_id"], unique=True, where="facility_id IS NULL")
    _ensure_index(bind, "patient_route_configurations", "uq_patient_route_config_tenant_facility", ["tenant_id", "facility_id"], unique=True, where="facility_id IS NOT NULL")


def _upgrade_routes(bind) -> None:
    columns = [sa.Column("id", _uuid(), primary_key=True), sa.Column("visit_id", _uuid(), nullable=False), sa.Column("consultation_id", _uuid()), sa.Column("patient_id", _uuid(), nullable=False), sa.Column("uhid", sa.String(20), nullable=False), sa.Column("facility_id", _uuid(), nullable=False), sa.Column("status", sa.String(40), nullable=False, server_default="AWAITING_PATIENT"), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]
    _create_table_if_absent(bind, "patient_routes", columns)
    for column in columns:
        _compatible_column(bind, "patient_routes", column)
    _ensure_primary_key(bind, "patient_routes", ["id"])
    _ensure_foreign_key(bind, "patient_routes", "fk_patient_routes_visit", ["visit_id"], "visits", ["id"])
    _ensure_foreign_key(bind, "patient_routes", "fk_patient_routes_consultation", ["consultation_id"], "consultations", ["id"])
    _ensure_foreign_key(bind, "patient_routes", "fk_patient_routes_patient", ["patient_id"], "patients", ["id"])
    _ensure_unique(bind, "patient_routes", "uq_patient_routes_visit", ["visit_id"])
    _ensure_check(bind, "patient_routes", "ck_patient_routes_status", "status IN ('AWAITING_PATIENT','IN_PROGRESS','COMPLETED','TERMINAL')", 'SELECT COUNT(*) FROM "patient_routes" WHERE status NOT IN (\'AWAITING_PATIENT\',\'IN_PROGRESS\',\'COMPLETED\',\'TERMINAL\')')
    for name, cols in (("ix_patient_routes_visit_id", ["visit_id"]), ("ix_patient_routes_patient_id", ["patient_id"]), ("ix_patient_routes_facility_id", ["facility_id"]), ("ix_patient_routes_patient_status", ["patient_id", "status"])):
        _ensure_index(bind, "patient_routes", name, cols)


def _upgrade_steps(bind) -> None:
    columns = [sa.Column("id", _uuid(), primary_key=True), sa.Column("route_id", _uuid(), nullable=False), sa.Column("visit_id", _uuid(), nullable=False), sa.Column("destination", sa.String(20), nullable=False), sa.Column("source_type", sa.String(40)), sa.Column("source_record_id", _uuid()), sa.Column("source_record_ids", _jsonb()), sa.Column("status", sa.String(40), nullable=False, server_default="AWAITING_PATIENT"), sa.Column("presentation_deadline_at", sa.DateTime(timezone=True)), sa.Column("presented_at", sa.DateTime(timezone=True)), sa.Column("service_started_at", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("not_presented_at", sa.DateTime(timezone=True)), sa.Column("reopened_at", sa.DateTime(timezone=True)), sa.Column("presented_by_user_id", _uuid()), sa.Column("reopened_by_user_id", _uuid()), sa.Column("presentation_channel", sa.String(30)), sa.Column("outcome_reason", sa.Text()), sa.Column("late_presentation", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]
    _create_table_if_absent(bind, "patient_route_steps", columns)
    for column in columns:
        _compatible_column(bind, "patient_route_steps", column)
    _ensure_primary_key(bind, "patient_route_steps", ["id"])
    _ensure_foreign_key(bind, "patient_route_steps", "fk_patient_route_steps_route", ["route_id"], "patient_routes", ["id"], ondelete="CASCADE")
    _ensure_foreign_key(bind, "patient_route_steps", "fk_patient_route_steps_visit", ["visit_id"], "visits", ["id"])
    _ensure_unique(bind, "patient_route_steps", "uq_patient_route_steps_destination", ["route_id", "destination"])
    _ensure_check(bind, "patient_route_steps", "ck_patient_route_steps_destination", "destination IN ('PHARMACY','LAB','BILLING','EXIT')", 'SELECT COUNT(*) FROM "patient_route_steps" WHERE destination NOT IN (\'PHARMACY\',\'LAB\',\'BILLING\',\'EXIT\')')
    _ensure_check(bind, "patient_route_steps", "ck_patient_route_steps_status", "status IN ('AWAITING_PATIENT','PRESENTED','PRESENTED_LATE','IN_SERVICE','COMPLETED','NOT_PRESENTED','DECLINED','EXTERNAL_PURCHASE_CONFIRMED','EXTERNAL_LAB_CONFIRMED','CANCELLED')", 'SELECT COUNT(*) FROM "patient_route_steps" WHERE status NOT IN (\'AWAITING_PATIENT\',\'PRESENTED\',\'PRESENTED_LATE\',\'IN_SERVICE\',\'COMPLETED\',\'NOT_PRESENTED\',\'DECLINED\',\'EXTERNAL_PURCHASE_CONFIRMED\',\'EXTERNAL_LAB_CONFIRMED\',\'CANCELLED\')')
    for name, cols in (("ix_patient_route_steps_route_id", ["route_id"]), ("ix_patient_route_steps_visit_id", ["visit_id"]), ("ix_patient_route_steps_lookup", ["destination", "status", "presentation_deadline_at"])):
        _ensure_index(bind, "patient_route_steps", name, cols)


def _upgrade_events(bind) -> None:
    columns = [sa.Column("id", _uuid(), primary_key=True), sa.Column("route_id", _uuid(), nullable=False), sa.Column("step_id", _uuid()), sa.Column("event_type", sa.String(50), nullable=False), sa.Column("previous_state", sa.String(40)), sa.Column("new_state", sa.String(40), nullable=False), sa.Column("actor_user_id", _uuid()), sa.Column("reason", sa.Text()), sa.Column("channel", sa.String(30)), sa.Column("request_id", sa.String(100)), sa.Column("metadata_json", _jsonb()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]
    _create_table_if_absent(bind, "patient_route_events", columns)
    for column in columns:
        _compatible_column(bind, "patient_route_events", column)
    _ensure_primary_key(bind, "patient_route_events", ["id"])
    _ensure_foreign_key(bind, "patient_route_events", "fk_patient_route_events_route", ["route_id"], "patient_routes", ["id"], ondelete="CASCADE")
    _ensure_foreign_key(bind, "patient_route_events", "fk_patient_route_events_step", ["step_id"], "patient_route_steps", ["id"], ondelete="CASCADE")
    for name, cols in (("ix_patient_route_events_route_id", ["route_id"]), ("ix_patient_route_events_step_time", ["step_id", "created_at"]), ("ix_patient_route_events_request_id", ["request_id"])):
        _ensure_index(bind, "patient_route_events", name, cols)


def _upgrade_documents(bind) -> None:
    columns = [sa.Column("id", _uuid(), primary_key=True), sa.Column("prescription_id", _uuid(), nullable=False), sa.Column("visit_id", _uuid(), nullable=False), sa.Column("snapshot_json", _jsonb(), nullable=False), sa.Column("status", sa.String(30), nullable=False, server_default="PENDING_GENERATION"), sa.Column("document_version_id", _uuid()), sa.Column("failure_reason", sa.Text()), sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("generated_at", sa.DateTime(timezone=True)), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]
    _create_table_if_absent(bind, "prescription_document_requests", columns)
    for column in columns:
        _compatible_column(bind, "prescription_document_requests", column)
    _ensure_primary_key(bind, "prescription_document_requests", ["id"])
    _ensure_foreign_key(bind, "prescription_document_requests", "fk_prescription_document_requests_prescription", ["prescription_id"], "prescriptions", ["id"])
    _ensure_foreign_key(bind, "prescription_document_requests", "fk_prescription_document_requests_visit", ["visit_id"], "visits", ["id"])
    _ensure_unique(bind, "prescription_document_requests", "uq_prescription_document_requests_prescription", ["prescription_id"])
    for name, cols in (("ix_prescription_document_requests_prescription_id", ["prescription_id"]), ("ix_prescription_document_requests_visit_id", ["visit_id"])):
        _ensure_index(bind, "prescription_document_requests", name, cols)


def upgrade() -> None:
    bind = op.get_bind()
    if not _is_tenant(bind):
        return
    _upgrade_config(bind)
    _upgrade_routes(bind)
    _upgrade_steps(bind)
    _upgrade_events(bind)
    _upgrade_documents(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if not _is_tenant(bind):
        return
    for table in ("prescription_document_requests", "patient_route_events", "patient_route_steps", "patient_routes", "patient_route_configurations"):
        if not _has_table(bind, table):
            continue
        if _table_owned(bind, table):
            op.drop_table(table)
            continue
        for index in _indexes(bind, table):
            if index.get("name", "").startswith(("ix_patient_route_", "uq_patient_route_config_", "ix_prescription_document_requests_")):
                op.drop_index(index["name"], table_name=table)
        for constraint in _checks(bind, table):
            if constraint.get("name", "").startswith("ck_patient_route"):
                op.drop_constraint(constraint["name"], table, type_="check")
        for constraint in _unique_constraints(bind, table):
            if constraint.get("name", "").startswith(("uq_patient_route", "uq_prescription_document_requests")):
                op.drop_constraint(constraint["name"], table, type_="unique")
