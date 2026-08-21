"""Concurrency-safe token allocation: tenant timezone + token_counters + queue_tokens uniqueness."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()

    if current_schema == "public":
        op.add_column(
            "tenants",
            sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Kolkata"),
            schema="public",
        )
        return

    inspector = sa.inspect(bind)

    if not inspector.has_table("token_counters"):
        op.create_table(
            "token_counters",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("scope_key", sa.String(length=120), nullable=False),
            sa.Column("counter_date", sa.Date(), nullable=False),
            sa.Column("last_value", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_unique_constraint(
            "uq_token_counters_scope_date", "token_counters", ["scope_key", "counter_date"]
        )

    existing_columns = {c["name"] for c in inspector.get_columns("queue_tokens")}
    if "token_date" not in existing_columns:
        op.add_column("queue_tokens", sa.Column("token_date", sa.Date(), nullable=True))
        op.execute("UPDATE queue_tokens SET token_date = issued_at::date WHERE token_date IS NULL")
        op.alter_column("queue_tokens", "token_date", nullable=False)

    if "token_scope" not in existing_columns:
        op.add_column("queue_tokens", sa.Column("token_scope", sa.String(length=120), nullable=True))
        op.execute(
            """
            UPDATE queue_tokens
               SET token_scope = CASE
                   WHEN department_id IS NOT NULL THEN 'dept:' || department_id::text
                   ELSE 'queue:' || queue_type
               END
             WHERE token_scope IS NULL
            """
        )
        op.alter_column("queue_tokens", "token_scope", nullable=False)

    existing_constraints = {c["name"] for c in inspector.get_unique_constraints("queue_tokens")}
    if "uq_queue_tokens_scope_date_token_no" not in existing_constraints:
        op.create_unique_constraint(
            "uq_queue_tokens_scope_date_token_no",
            "queue_tokens",
            ["token_scope", "token_date", "token_no"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()

    if current_schema == "public":
        op.drop_column("tenants", "timezone", schema="public")
        return

    inspector = sa.inspect(bind)

    existing_constraints = {c["name"] for c in inspector.get_unique_constraints("queue_tokens")}
    if "uq_queue_tokens_scope_date_token_no" in existing_constraints:
        op.drop_constraint("uq_queue_tokens_scope_date_token_no", "queue_tokens", type_="unique")

    existing_columns = {c["name"] for c in inspector.get_columns("queue_tokens")}
    if "token_scope" in existing_columns:
        op.drop_column("queue_tokens", "token_scope")
    if "token_date" in existing_columns:
        op.drop_column("queue_tokens", "token_date")

    if inspector.has_table("token_counters"):
        op.drop_table("token_counters")
