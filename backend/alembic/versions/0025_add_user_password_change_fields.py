"""Add password-change enforcement fields to public.users.

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-12 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            ALTER TABLE public.users
                ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT TRUE;
            """
        )
    )
    conn.execute(
        sa.text(
            """
            ALTER TABLE public.users
                ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMP NULL;
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE public.users
               SET must_change_password = FALSE
             WHERE must_change_password IS NULL OR must_change_password = TRUE;
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            ALTER TABLE public.users
                DROP COLUMN IF EXISTS password_changed_at;
            """
        )
    )
    conn.execute(
        sa.text(
            """
            ALTER TABLE public.users
                DROP COLUMN IF EXISTS must_change_password;
            """
        )
    )
