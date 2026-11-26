from unittest.mock import Mock

import pytest

from app.context_store import Snapshot
from app.hybrid_detection import HybridRouter, ModelReadiness, SnapshotFailure
from test_rule_detection import TRACE, completion


READY = ModelReadiness(checkpoint_available=True, runtime_available=True,
                       configuration_compatible=True, domain_validated=True,
                       approved_runtime_available=True)


def test_auto_uses_rules_when_domain_unverified():
    model = Mock()
    status, output = HybridRouter(model=model).route(TRACE, "AUTO", lambda _: Snapshot([completion(status=503)]))
    assert status == 200 and output.is_anomaly is True
    assert output.executed_mode == "RULE_BASED" and output.detection_source == "rule_based"
    assert output.fallback_used and output.fallback_reason == "DOMAIN_NOT_VALIDATED"
    assert output.model_score is None
    assert not model.mock_calls


def test_rules_do_not_inspect_model():
    model = Mock()
    router = HybridRouter(model=model, readiness=READY)
    router.blocker = Mock(side_effect=AssertionError)
    status, output = router.route(TRACE, "RULE_BASED", lambda _: Snapshot([completion()]))
    assert status == 200 and output.is_anomaly is False
    assert not output.fallback_used and output.fallback_reason is None
    assert output.model_readiness is None and output.model_score is None
    assert not model.mock_calls and not router.blocker.called


@pytest.mark.parametrize(("readiness", "reason"), [
    (ModelReadiness(), "DOMAIN_NOT_VALIDATED"),
    (READY.model_copy(update={"domain_validated": False}), "DOMAIN_NOT_VALIDATED"),
    (READY.model_copy(update={"runtime_available": False}), "MODEL_RUNTIME_UNAVAILABLE"),
    (READY.model_copy(update={"approved_runtime_available": False}), "MODEL_NOT_READY"),
    (READY.model_copy(update={"configuration_compatible": False}), "MODEL_NOT_READY"),
    (READY.model_copy(update={"checkpoint_available": False}), "MODEL_NOT_READY"),
])
def test_model_only_preserves_readiness_guard(readiness, reason):
    model, read, rule = Mock(), Mock(), Mock()
    status, output = HybridRouter(model=model, readiness=readiness, rule_engine=rule).route(
        TRACE, "MECOLOG_ONLY", read
    )
    assert status == 503 and output.error.code == "NOT_READY_FOR_SCORING"
    assert reason in output.diagnostics and not output.fallback_used
    assert output.model_score is None and output.is_anomaly is None and output.executed_mode is None
    assert not model.mock_calls and not read.called and not rule.called


@pytest.mark.parametrize(("error", "compatible", "reason", "strict_status"), [
    (None, False, "INPUT_INCOMPATIBLE", 422),
    (OSError("secret runtime"), True, "MODEL_RUNTIME_UNAVAILABLE", 503),
    (TimeoutError("secret timeout"), True, "MODEL_TIMEOUT", 504),
    (RuntimeError("secret execution"), True, "MODEL_EXECUTION_ERROR", 503),
])
@pytest.mark.parametrize("mode", ["AUTO", "MECOLOG_ONLY"])
def test_model_fallback_policy(error, compatible, reason, strict_status, mode):
    model = Mock()
    model.compatible.return_value = compatible
    model.detect.side_effect = error
    snapshot = Snapshot([completion(status=503)])
    read = Mock(return_value=snapshot)
    router = HybridRouter(model=model, readiness=READY)
    rule = Mock(wraps=router.rule_engine)
    router.rule_engine = rule
    status, output = router.route(TRACE, mode, read)
    read.assert_called_once_with(TRACE)
    assert model.detect.call_count == int(compatible)
    assert output.model_score is None
    assert "secret" not in output.model_dump_json()
    if mode == "AUTO":
        assert status == 200 and output.fallback_used and output.fallback_reason == reason
        assert output.executed_mode == "RULE_BASED"
        assert rule.call_args.args[1] is snapshot
    else:
        assert status == strict_status and reason in output.diagnostics
        assert not rule.called and not output.fallback_used and output.is_anomaly is None


@pytest.mark.parametrize("anomaly", [True, False])
def test_approved_model_double_stops_routing_after_decision(anomaly):
    rule, model = Mock(), Mock()
    model.compatible.return_value = True
    row = {**completion(), "ground_truth": "secret", "activation": "secret"}
    model.detect.return_value = {"is_anomaly": anomaly, "model_score": .25 if anomaly else -.25,
                                 "evidence_event_ids": [row["event_id"]]}
    status, output = HybridRouter(model=model, readiness=READY, rule_engine=rule).route(
        TRACE, "AUTO", lambda _: Snapshot([row])
    )
    assert status == 200 and output.is_anomaly is anomaly
    assert output.executed_mode == "MECOLOG_ONLY" and output.detection_source == "mecolog"
    assert output.model_score == model.detect.return_value["model_score"]
    assert output.rule_version is None and not output.fallback_used and not rule.called
    model.detect.assert_called_once()
    assert not hasattr(model.detect.call_args.args[0][0], "ground_truth")


@pytest.mark.parametrize("ids", [[], ["d" * 32]])
def test_model_evidence_is_validated(ids):
    model = Mock()
    model.compatible.return_value = True
    model.detect.return_value = {"is_anomaly": True, "model_score": .25, "evidence_event_ids": ids}
    status, output = HybridRouter(model=model, readiness=READY).route(
        TRACE, "AUTO", lambda _: Snapshot([completion()])
    )
    assert status == 200 and output.is_anomaly is False
    assert output.fallback_reason == "MODEL_EXECUTION_ERROR" and output.evidence_event_ids == []
    assert output.model_score is None


@pytest.mark.parametrize(("rows", "status", "context"), [
    ([], "INSUFFICIENT_DATA", "unknown"),
    ([{}], "INSUFFICIENT_DATA", "unknown"),
    ([completion(), completion()], "NO_ANOMALY_DETECTED", "partial"),
])
def test_rule_context_and_duplicates(rows, status, context):
    _, output = HybridRouter().route(TRACE, "AUTO", lambda _: Snapshot(rows))
    assert output.detection_status == status and output.context_completeness == context
    assert output.model_score is None and output.evidence_event_ids == []
    assert output.is_anomaly is (None if status == "INSUFFICIENT_DATA" else False)


def test_rule_failure_after_model_failure_remains_error():
    model, rule = Mock(), Mock(side_effect=RuntimeError("secret"))
    model.compatible.return_value = True
    model.detect.side_effect = TimeoutError
    status, output = HybridRouter(model=model, readiness=READY, rule_engine=rule).route(
        TRACE, "AUTO", lambda _: Snapshot([completion()])
    )
    assert status == 500 and output.detection_status == "DETECTION_ERROR"
    assert output.error.code == "RULE_EXECUTION_ERROR" and output.fallback_reason == "MODEL_TIMEOUT"
    assert output.is_anomaly is None and output.model_score is None
    assert "secret" not in output.model_dump_json()


def test_snapshot_failure_does_not_score_or_run_rules():
    rule, model = Mock(), Mock()
    status, output = HybridRouter(model=model, readiness=READY, rule_engine=rule).route(
        TRACE, "AUTO", Mock(side_effect=SnapshotFailure(503, "TRACE_STORE_UNAVAILABLE"))
    )
    assert status == 503 and output.executed_mode is None and output.detection_source == "none"
    assert output.is_anomaly is None and not output.fallback_used
    assert not rule.called and not model.mock_calls
