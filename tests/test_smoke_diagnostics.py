import json

from tools.smoke_diagnostics import extract_smoke_diagnostic, extract_validation_diagnostic


def test_extract_validation_diagnostic_discards_unapproved_log_fields():
    details = {
        "reason": "OBSERVATION_MISMATCH", "location": "evidence", "index": 1,
        "event_id": "a" * 32, "kind": "status", "expected": "502",
        "actual_safe": "HTTP 502", "actual_length": 8,
        "raw_output": "private-model-output",
    }
    log = "unrelated private value\nWARNING: llm_validation_failure " + json.dumps(details)
    captured = extract_validation_diagnostic(log)
    assert captured == {key: value for key, value in details.items() if key != "raw_output"}
    assert "private" not in json.dumps(captured)


def test_extract_validation_diagnostic_rejects_unsafe_generated_value():
    details = {
        "reason": "OBSERVATION_MISMATCH", "location": "observations", "index": 0,
        "event_id": "b" * 32, "kind": "message", "expected": "request_completed",
        "actual_safe": "private-model-output", "actual_length": 20,
    }
    assert extract_validation_diagnostic("llm_validation_failure " + json.dumps(details)) is None


def test_extract_non_observation_validation_reason_without_raw_fields():
    log = 'WARNING: llm_validation_failure {"reason":"SUSPECTED_SERVICE_UNGROUNDED",' \
          '"raw_output":"private-model-output"}'
    assert extract_smoke_diagnostic(log) == {
        "type": "validation", "reason": "SUSPECTED_SERVICE_UNGROUNDED"}


def test_extract_provider_diagnostic_keeps_only_allowlisted_metadata():
    details = {
        "category": "PROVIDER_UPSTREAM_ERROR", "failure_stage": "upstream_response",
        "upstream_http_status": 503, "provider_error_code": "UNAVAILABLE",
        "receipt_status": "CONFIRMED", "retryable": True,
        "sanitized_error_message": "private-model-output",
    }
    captured = extract_smoke_diagnostic("gemini_provider_failure " + json.dumps(details))
    assert captured == {"type": "provider", **{
        key: value for key, value in details.items() if key != "sanitized_error_message"}}
    assert "private" not in json.dumps(captured)
