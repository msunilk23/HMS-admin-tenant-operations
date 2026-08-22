"""Add immutable invoice document version table per tenant schema."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return

    inspector = sa.inspect(bind)
    if inspector.has_table("invoice_document_versions"):
        return

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


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(text("SELECT current_schema()")).scalar() == "public":
        return

    inspector = sa.inspect(bind)
    if not inspector.has_table("invoice_document_versions"):
        return

    op.drop_index("ix_invoice_document_versions_invoice_id", table_name="invoice_document_versions")
    op.drop_table("invoice_document_versions")
