import pytest
from fastapi import HTTPException

from app.models.tenant.lab_order import can_transition_lab_order


@pytest.mark.parametrize(
    ("current", "new"),
    [
        ("ordered", "sample_pending"),
        ("sample_pending", "sample_collected"),
        ("sample_collected", "processing"),
        ("processing", "result_ready"),
        ("result_ready", "verified"),
        ("verified", "completed"),
    ],
)
def test_lab_workflow_accepts_phase_13_transitions(current, new):
    assert can_transition_lab_order(current, new)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        ("ordered", "processing"),
        ("result_ready", "completed"),
        ("completed", "verified"),
        ("ordered", "unknown"),
    ],
)
def test_lab_workflow_rejects_skipped_or_unknown_transitions(current, new):
    assert not can_transition_lab_order(current, new)