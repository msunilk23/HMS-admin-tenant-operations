from datetime import datetime, timezone
from typing import Iterable


def queue_stage_summary(
    visits: Iterable[object],
    *,
    queue_timestamp: str,
    threshold_seconds: int,
    now: datetime | None = None,
) -> dict:
    current = now or datetime.now(timezone.utc)
    waits = []
    for visit in visits:
        queued_at = getattr(visit, queue_timestamp, None)
        if queued_at is None:
            continue
        if queued_at.tzinfo is None:
            queued_at = queued_at.replace(tzinfo=timezone.utc)
        wait_seconds = max((current - queued_at.astimezone(timezone.utc)).total_seconds(), 0.0)
        waits.append(wait_seconds)
    return {
        "waiting_count": len(waits),
        "breached_count": sum(wait >= threshold_seconds for wait in waits),
        "longest_wait_seconds": max(waits) if waits else None,
        "sla_threshold_seconds": threshold_seconds,
    }
