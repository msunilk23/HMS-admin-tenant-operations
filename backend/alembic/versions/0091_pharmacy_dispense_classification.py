"""Classify OPD prescription dispensing without retail duplication.

Revision ID: 0091
Revises: 0090
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "0091"
down_revision = "0090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    schema = bind.execute(text("SELECT current_schema()" )).scalar_one()
    if schema == "public":
        return

    op.add_column(
        "pharmacy_dispenses",
        sa.Column("classification", sa.String(length=30), nullable=False, server_default="OPD_PRESCRIPTION"),
    )
    op.create_check_constraint(
        "ck_pharmacy_dispenses_classification",
        "pharmacy_dispenses",
        "classification = 'OPD_PRESCRIPTION'",
    )


def downgrade() -> None:
    bind = op.get_bind()
    schema = bind.execute(text("SELECT current_schema()" )).scalar_one()
    if schema == "public":
        return

    op.drop_constraint(
        "ck_pharmacy_dispenses_classification",
        "pharmacy_dispenses",
        type_="check",
    )
    op.drop_column("pharmacy_dispenses", "classification")