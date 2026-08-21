"""
Concurrency-safe daily token allocation service.

Single source of truth for OPD token numbering — both walk-in registration
(queue.py) and appointment check-in (appointments.py) must call this module
instead of maintaining their own MAX(token_no)+1 logic, which is subject to a
lost-update race under concurrent registration.

Numbering is scoped per (tenant schema via search_path) + department (when
applicable) or queue_type (when department is not applicable), and resets
daily using the tenant's configured IANA timezone rather than UTC midnight.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant.queue_token import QueueToken
from app.models.tenant.token_counter import TokenCounter

DEFAULT_TENANT_TIMEZONE = "Asia/Kolkata"

# The atomic counter already serializes concurrent callers; a handful of
# retries only guards against the (very unlikely) case of the queue_tokens
# unique constraint firing for some other reason.
_MAX_ALLOCATION_ATTEMPTS = 5


class TokenAllocationConflict(Exception):
    """Raised when a unique token number could not be established after retrying."""


def department_scope(department_id: uuid.UUID) -> str:
    return f"dept:{department_id}"


def queue_type_scope(queue_type: str) -> str:
    return f"queue:{queue_type}"


def resolve_scope(queue_type: str, department_id: uuid.UUID | None) -> str:
    return department_scope(department_id) if department_id else queue_type_scope(queue_type)


def tenant_local_date(tenant_timezone: str | None) -> date:
    """Tenant's current calendar date in its configured IANA timezone (not UTC)."""
    try:
        tz = ZoneInfo(tenant_timezone or DEFAULT_TENANT_TIMEZONE)
    except ZoneInfoNotFoundError:
        tz = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(tz).date()


async def _allocate_token_number(session: AsyncSession, scope_key: str, counter_date: date) -> int:
    """
    Atomically increment and return the next token number for (scope_key, counter_date).

    Implemented as a single INSERT ... ON CONFLICT DO UPDATE ... RETURNING
    statement so PostgreSQL row-level locking serializes concurrent callers
    instead of a lost-update race (the previous MAX(token_no)+1 approach could
    hand out the same number to two concurrent requests). SQLite (used by
    fast in-process unit tests) supports the same upsert syntax, so the same
    code path works for both without weakening the Postgres guarantee.
    """
    bind = session.bind
    insert_fn = _sqlite_insert if bind is not None and bind.dialect.name == "sqlite" else _pg_insert
    stmt = (
        insert_fn(TokenCounter)
        .values(id=uuid.uuid4(), scope_key=scope_key, counter_date=counter_date, last_value=1)
        .on_conflict_do_update(
            index_elements=["scope_key", "counter_date"],
            set_={"last_value": TokenCounter.last_value + 1},
        )
        .returning(TokenCounter.last_value)
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def allocate_and_create_token(
    session: AsyncSession,
    token_factory: Callable[[int, str, date], QueueToken],
    queue_type: str,
    department_id: uuid.UUID | None,
    tenant_timezone: str | None,
) -> QueueToken:
    """
    Allocate a concurrency-safe token number and flush the resulting QueueToken row.

    `token_factory(token_no, token_scope, token_date) -> QueueToken` must
    construct (but not add/flush) a QueueToken using the given values.
    Does not commit — caller controls the surrounding transaction so token
    and visit creation remain atomic.
    """
    scope_key = resolve_scope(queue_type, department_id)
    counter_date = tenant_local_date(tenant_timezone)

    last_error: Exception | None = None
    for _ in range(_MAX_ALLOCATION_ATTEMPTS):
        token_no = await _allocate_token_number(session, scope_key, counter_date)
        token = token_factory(token_no, scope_key, counter_date)
        nested = await session.begin_nested()
        try:
            session.add(token)
            await session.flush()
        except IntegrityError as exc:
            await nested.rollback()
            try:
                session.expunge(token)
            except Exception:
                pass
            last_error = exc
            continue
        return token

    raise TokenAllocationConflict(
        "Could not allocate a unique token number after multiple attempts"
    ) from last_error
