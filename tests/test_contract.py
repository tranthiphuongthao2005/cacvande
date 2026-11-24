import pytest
from pydantic import ValidationError

from app.contracts import DetectionSession


def test_detection_contract_rejects_ground_truth_and_bad_time_order():
    stamp = "2026-01-01T12:00:00Z"
    payload = dict(session_id="trace:01", trace_id="1"*32, service_name="order",
                   start_time=stamp, end_time=stamp,
                   events=[dict(event_id="001", timestamp=stamp, service_name="user", level="INFO",
                                event_name="request_completed", message="completed GET user")],
                   source_metadata=dict(environment="lab", collector="source", completeness="complete"))
    assert DetectionSession.model_validate(payload).events[0].service_name == "user"
    with pytest.raises(ValidationError):
        DetectionSession.model_validate({**payload, "scenario_id": "fixture"})
    with pytest.raises(ValidationError):
        DetectionSession.model_validate({**payload, "end_time": "2026-01-01T11:00:00Z"})
