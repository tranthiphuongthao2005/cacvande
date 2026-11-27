"""Capture only allowlisted validation details from a smoke container's logs."""

import json
import re
import subprocess

from app.trace_store import EVENTS


MARKER = "llm_validation_failure "
PROVIDER_MARKER = "gemini_provider_failure "
EVENT_ID = re.compile(r"^[0-9a-f]{32}$")
STATUS = re.compile(r"^(?:HTTP )?[1-5][0-9]{2}$")
CODE = re.compile(r"^[A-Z_]+$")
VALIDATION_REASONS = frozenset({
    "DISALLOWED_CONTENT", "OUT_OF_SCOPE_EVIDENCE", "OBSERVATION_MISMATCH",
    "EVIDENCE_MISMATCH", "AFFECTED_SERVICE_UNGROUNDED", "INVALID_SUSPECTED_CAUSE",
    "HYPOTHESIS_UNGROUNDED", "SUSPECTED_SERVICE_UNGROUNDED", "MISSING_OBSERVATIONS",
    "UNCLASSIFIED",
})


def safe_value(value):
    return value is None or (isinstance(value, str) and (
        value in EVENTS or value in {"user", "product", "order"}
        or STATUS.fullmatch(value) is not None))


def extract_validation_diagnostic(log_text):
    for line in reversed(log_text.splitlines()):
        if MARKER not in line:
            continue
        try:
            details = json.loads(line.split(MARKER, 1)[1])
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(details, dict) or details.get("reason") not in VALIDATION_REASONS:
            continue
        if details["reason"] != "OBSERVATION_MISMATCH":
            return {"reason": details["reason"]}
        if (details.get("location") not in {"observations", "evidence"}
                or type(details.get("index")) is not int or details["index"] < 0
                or not isinstance(details.get("event_id"), str)
                or not EVENT_ID.fullmatch(details["event_id"])
                or details.get("kind") not in {"message", "status", "dependency_failure"}
                or not safe_value(details.get("expected"))
                or not safe_value(details.get("actual_safe"))
                or type(details.get("actual_length")) is not int
                or details["actual_length"] < 0):
            continue
        return {key: details[key] for key in (
            "reason", "location", "index", "event_id", "kind", "expected",
            "actual_safe", "actual_length")}
    return None


def extract_smoke_diagnostic(log_text):
    validation = extract_validation_diagnostic(log_text)
    if validation is not None:
        return {"type": "validation", **validation}
    for line in reversed(log_text.splitlines()):
        if PROVIDER_MARKER not in line:
            continue
        try:
            details = json.loads(line.split(PROVIDER_MARKER, 1)[1])
        except (json.JSONDecodeError, ValueError):
            continue
        if (not isinstance(details, dict)
                or not isinstance(details.get("category"), str)
                or not CODE.fullmatch(details["category"])
                or not isinstance(details.get("failure_stage"), str)
                or not re.fullmatch(r"[a-z_]+", details["failure_stage"])
                or (details.get("upstream_http_status") is not None
                    and (type(details["upstream_http_status"]) is not int
                         or not 400 <= details["upstream_http_status"] <= 599))
                or (details.get("provider_error_code") is not None
                    and (not isinstance(details["provider_error_code"], str)
                         or not CODE.fullmatch(details["provider_error_code"])))
                or details.get("receipt_status") not in {"UNKNOWN", "CONFIRMED"}
                or (details.get("retryable") is not None
                    and type(details["retryable"]) is not bool)):
            continue
        return {"type": "provider", **{key: details.get(key) for key in (
            "category", "failure_stage", "upstream_http_status", "provider_error_code",
            "receipt_status", "retryable")}}
    return None


def capture_smoke_diagnostic(since_utc, container="thesis-log-anomaly-llm-service-1"):
    try:
        result = subprocess.run(
            ("docker", "logs", "--since", since_utc, container),
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    return extract_smoke_diagnostic(result.stdout + "\n" + result.stderr)
