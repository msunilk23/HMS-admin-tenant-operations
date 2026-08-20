from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.nurse_roster import NurseRosterCreate
from app.services.tat import build_visit_tat


UTC = timezone.utc


def test_roster_requires_supported_shift():
    with pytest.raises(ValidationError):
        NurseRosterCreate(
            user_id="00000000-0000-0000-0000-000000000001",
            roster_date=date(2026, 8, 13),
            shift="split",
            department_id="00000000-0000-0000-0000-000000000002",
        )


def test_tat_calculations_use_persisted_stage_timestamps():
    start = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)
    visit = SimpleNamespace(
        registered_at=start,
        nurse_queue_at=start + timedelta(minutes=5),
        nurse_called_at=start + timedelta(minutes=15),
        pre_vital_started_at=start + timedelta(minutes=15),
        pre_vital_completed_at=start + timedelta(minutes=30),
        doctor_queue_at=start + timedelta(minutes=30),
        doctor_called_at=start + timedelta(minutes=45),
        consultation_started_at=start + timedelta(minutes=45),
        consultation_completed_at=start + timedelta(minutes=75),
        billing_started_at=start + timedelta(minutes=80),
        billing_completed_at=start + timedelta(minutes=90),
        closed_at=start + timedelta(minutes=90),
    )
    lab = SimpleNamespace(ordered_at=start, result_ready_at=start + timedelta(hours=2))
    pharmacy = SimpleNamespace(called_at=start + timedelta(hours=1), dispensed_at=start + timedelta(hours=2))
    invoice = SimpleNamespace(billing_started_at=visit.billing_started_at, billing_completed_at=visit.billing_completed_at)

    result = build_visit_tat(visit, lab_order=lab, pharmacy_queue=pharmacy, invoice=invoice)

    assert result["nurse_wait_seconds"] == 600
    assert result["pre_vitals_seconds"] == 900
    assert result["doctor_wait_seconds"] == 900
    assert result["consultation_seconds"] == 1800
    assert result["lab_wait_seconds"] == 7200
    assert result["billing_seconds"] == 600
    assert result["total_opd_seconds"] == 5400
