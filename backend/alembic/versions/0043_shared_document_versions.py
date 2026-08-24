"""Shared immutable document architecture (invoice + prescription PDFs).

Replaces the invoice-only `invoice_document_versions` table (migration 0042)
with a generic `document_versions` table used by both invoice and
prescription PDFs, plus `document_version_counters` backing concurrency-safe
version allocation (Task F — row-locked atomic counter, same pattern as
`token_counters` from migration 0037).

No production data exists yet for `invoice_document_versions` at this stage
of Phase 1 stabilization, so this is a straight replace-not-migrate-data
change; if that ever changes, a follow-up corrective migration should backfill
`document_versions` from the old table before it is dropped.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0043_shared_documents"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return

    inspector = sa.inspect(bind)

    if inspector.has_table("invoice_document_versions"):
        op.drop_index("ix_invoice_document_versions_invoice_id", table_name="invoice_document_versions")
        op.drop_table("invoice_document_versions")

    if not inspector.has_table("document_versions"):
        op.create_table(
            "document_versions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("document_type", sa.String(length=30), nullable=False),
            sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
            sa.Column("snapshot_checksum", sa.String(length=64), nullable=False),
            sa.Column("storage_key", sa.String(length=400), nullable=False),
            sa.Column("file_size_bytes", sa.Integer(), nullable=False),
            sa.Column("snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("generated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("generated_by_service", sa.String(length=80), nullable=True),
            sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("document_type", "parent_id", "version", name="uq_document_versions_type_parent_version"),
            sa.UniqueConstraint("document_type", "storage_key", name="uq_document_versions_storage_key"),
        )
        op.create_index(
            "ix_document_versions_type_parent", "document_versions", ["document_type", "parent_id"]
        )
        op.create_index(
            "ix_document_versions_snapshot_checksum", "document_versions", ["snapshot_checksum"]
        )

    if not inspector.has_table("document_version_counters"):
        op.create_table(
            "document_version_counters",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("document_type", sa.String(length=30), nullable=False),
            sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("last_value", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("document_type", "parent_id", name="uq_document_version_counters_type_parent"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return

    inspector = sa.inspect(bind)

    if inspector.has_table("document_version_counters"):
        op.drop_table("document_version_counters")

    if inspector.has_table("document_versions"):
        op.drop_index("ix_document_versions_type_parent", table_name="document_versions")
        op.drop_table("document_versions")

    if not inspector.has_table("invoice_document_versions"):
        op.create_table(
            "invoice_document_versions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
            sa.Column("storage_path", sa.Text(), nullable=False),
            sa.Column("file_size_bytes", sa.Integer(), nullable=False),
            sa.Column("snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("invoice_id", "version", name="uq_invoice_doc_invoice_version"),
            sa.UniqueConstraint("invoice_id", "checksum_sha256", name="uq_invoice_doc_invoice_checksum"),
        )
        op.create_index("ix_invoice_document_versions_invoice_id", "invoice_document_versions", ["invoice_id"])
