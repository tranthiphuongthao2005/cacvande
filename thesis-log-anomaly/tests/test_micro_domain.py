import pytest

from app.micro_dataset import groups_for, propose_assignment, validate_assignment
from app.micro_parser import parse_event
from app.trace_store import TraceStore


def make_session(trace, event_id, service, message):
    return TraceStore(None).session(trace, [{
        "trace_id": trace, "event_id": event_id, "service_name": service, "message": message,
        "status_code": 200, "level": "INFO", "@timestamp": "2026-11-22T17:00:00Z",
    }])


def test_parser_uses_observed_message_and_preserves_lineage():
    for service in ("user", "product", "order"):
        session = make_session("a" * 32, "sample", service, "request_completed")
        event = session.events[0]
        expected = parse_event(session.trace_id, event)
        assert expected.template == f"{service} request completed"
        assert (expected.trace_id, expected.event_id, expected.status) == ("a" * 32, "sample", 200)
        assert expected == parse_event(session.trace_id, event)
        unrelated = event.model_copy(update={"message": "expected_root_cause=private"})
        unknown = parse_event(session.trace_id, unrelated)
        assert unknown.unknown_template and "private" not in unknown.template


def test_family_and_observed_signatures_cannot_cross_split():
    first = make_session("a" * 32, "one", "order", "request_completed")
    second = make_session("b" * 32, "two", "order", "request_completed")
    third = make_session("c" * 32, "three", "product", "request_completed")
    data = {"first": first, "second": second, "third": third}
    labels = {"first": {"family": "normal"}, "second": {"family": "other"}, "third": {"family": "other"}}
    assert len(set(groups_for(data, labels).values())) == 1
    split = {"support": ["first"], "development": ["second"], "evaluation": ["third"]}
    with pytest.raises(ValueError, match="leakage"):
        validate_assignment(data, labels, split)


def test_split_can_accept_independent_groups():
    observations, labels = {}, {}
    for i, service in enumerate(("user", "product", "order")):
        for label, message in enumerate(("request_completed", "request_failed")):
            name = f"{service}{label}"
            observations[name] = make_session(f"{i * 2 + label + 1:032x}", name, service, message)
            labels[name] = {"family": name, "label": label, "fault_type": message}
    assignment = propose_assignment(observations, labels, 123)
    assert assignment == propose_assignment(dict(reversed(list(observations.items()))), labels, 123)
    assert all(row["normal"] == row["anomaly"] == 1
               for row in validate_assignment(observations, labels, assignment).values())
