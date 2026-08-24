"""Harden migration 0037 (queue-token concurrency): timezone-correct token_date
backfill and deterministic duplicate remediation.

Task G finding: 0037 backfilled `token_date` with `issued_at::date`, which
implicitly relies on whatever timezone the migration's DB session happens to
have (PostgreSQL casts `timestamptz::date` using the *session* TimeZone GUC,
not the tenant's configured IANA timezone) before adding a unique constraint
on (token_scope, token_date, token_no) with no prior duplicate check. Per the
forward-only migration policy this is fixed with a corrective migration
rather than editing 0037.

This migration, for every tenant schema:
  1. Recomputes token_date from `issued_at` explicitly converted to the
     tenant's own timezone (looked up from public.tenants.timezone by
     schema name) — correct regardless of session timezone, and correct for
     tokens issued right around local midnight.
  2. Detects any (token_scope, token_date, token_no) duplicates the
     corrected dates create/expose and deterministically remediates them:
     the earliest-issued row in each conflicting group keeps its number;
     later duplicates are renumbered to the next free number in that
     (scope, date) bucket, ordered by issued_at then id. Renumbering is done
     via a temporary offset first so it can never transiently collide with
     the existing unique constraint from 0037.

No schema/index changes here — this is a data-correction migration, so
downgrade is a documented no-op (the corrected dates/numbers are strictly
more accurate than what 0037 produced and are not meaningfully reversible).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

_RENUMBER_OFFSET = 1_000_000


def upgrade() -> None:
    bind = op.get_bind()
    current_schema = bind.execute(text("SELECT current_schema()")).scalar()
    if current_schema == "public":
        return

    inspector = sa.inspect(bind)
    if not inspector.has_table("queue_tokens"):
        return

    tenant_tz = bind.execute(
        text("SELECT timezone FROM public.tenants WHERE schema_name = :schema"),
        {"schema": current_schema},
    ).scalar() or "Asia/Kolkata"

    # issued_at is timestamptz (stored/compared internally in UTC). A single
    # `AT TIME ZONE tz` conversion of a timestamptz value produces the naive
    # local wall-clock timestamp in that zone; casting that (already-local)
    # naive timestamp to ::date is then correct regardless of the session's
    # TimeZone GUC, including for tokens issued right around local midnight
    # where a UTC-based cast would land on the wrong calendar day.
    # (Note: chaining an extra `AT TIME ZONE 'UTC'` first would be wrong here —
    # applying AT TIME ZONE to an already-naive timestamp REINTERPRETS it as
    # being in that zone and converts back to timestamptz, the opposite of
    # what's needed.)
    bind.execute(
        text(
            "UPDATE queue_tokens "
            "SET token_date = (issued_at AT TIME ZONE :tz)::date"
        ),
        {"tz": tenant_tz},
    )

    duplicate_groups = bind.execute(
        text(
            """
            SELECT token_scope, token_date, token_no,
                   array_agg(id ORDER BY issued_at, id) AS ids
              FROM queue_tokens
             GROUP BY token_scope, token_date, token_no
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()

    if duplicate_groups:
        # Phase 1: move every duplicate-but-one to a collision-free temporary
        # range so phase 2 can never transiently violate the unique constraint.
        offset_counter = 0
        pending: list[tuple] = []
        for _scope, _tdate, _tno, ids in duplicate_groups:
            for stray_id in ids[1:]:
                offset_counter += 1
                bind.execute(
                    text("UPDATE queue_tokens SET token_no = :n WHERE id = :id"),
                    {"n": _RENUMBER_OFFSET + offset_counter, "id": stray_id},
                )
                pending.append((stray_id,))

        # Phase 2: assign each temporarily-offset row the next free token_no
        # in its own (token_scope, token_date) bucket, deterministically
        # ordered by issued_at so remediation is reproducible.
        for scope, tdate, _tno, ids in duplicate_groups:
            next_no = bind.execute(
                text(
                    "SELECT COALESCE(MAX(token_no), 0) FROM queue_tokens "
                    "WHERE token_scope = :s AND token_date = :d AND token_no < :offset"
                ),
                {"s": scope, "d": tdate, "offset": _RENUMBER_OFFSET},
            ).scalar() + 1
            for stray_id in ids[1:]:
                bind.execute(
                    text("UPDATE queue_tokens SET token_no = :n WHERE id = :id"),
                    {"n": next_no, "id": stray_id},
                )
                next_no += 1


def downgrade() -> None:
    # Data-correction only (no schema change) — see module docstring.
    pass
