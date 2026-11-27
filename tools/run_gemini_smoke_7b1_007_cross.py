"""Run the approved Gemini Cross-Service call after a passing Single-Service call."""

import hashlib
import json
from datetime import datetime, timezone

import httpx
from pydantic import ValidationError

from app.llm_analysis import AnalysisRequest, IncidentAnalysis, prepare
from tools.raw_smoke_capture import copy_one_raw_response
from tools.run_gemini_smoke_7b1_007_single import ROOT, SMOKE, read, stop_llm, write_new
from tools.smoke_diagnostics import capture_smoke_diagnostic


APPROVAL = SMOKE / "gemini-smoke-7b1-007.json"
ACTIVATION = SMOKE / "gemini-smoke-7b1-007.activation.json"
SINGLE_RESULT = SMOKE / "gemini-smoke-7b1-007.single.result.json"
ATTEMPT = SMOKE / "gemini-smoke-7b1-007.cross.attempt.json"
RESULT = SMOKE / "gemini-smoke-7b1-007.cross.result.json"


def main():
    approval = read(APPROVAL)
    activation = read(ACTIVATION)
    single = read(SINGLE_RESULT)
    if ATTEMPT.exists() or RESULT.exists():
        raise RuntimeError("Cross-Service attempt already exists")
    if (single["approval_id"] != approval["approval_id"]
            or single["status"] != "PASS"
            or activation["approval_id"] != approval["approval_id"]
            or approval.get("raw_capture", {}).get("mode") != "ONE_FAILED_RESPONSE"
            or activation.get("raw_capture_enabled") is not True):
        raise RuntimeError("Passing Single-Service result and matching activation required")
    now = datetime.now(timezone.utc)
    if now >= datetime.fromisoformat(activation["expires_at_utc"]):
        raise RuntimeError("Smoke activation expired")
    if (now - datetime.fromisoformat(single["completed_at_utc"])).total_seconds() < 10:
        raise RuntimeError("Minimum interval between Gemini calls is 10 seconds")

    source = approval["inputs"]["cross_service"]
    source_path = ROOT / source["path"]
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != source["sha256"]:
        raise RuntimeError("Approved Cross-Service Context snapshot changed")

    trace = approval["trace_id"]
    query = AnalysisRequest(trace_id=trace, mode="cross_service")
    request = {"trace_id": trace, "mode": "cross_service"}
    with httpx.Client(timeout=30, trust_env=False) as client:
        ready = client.get("http://127.0.0.1:8016/ready").raise_for_status().json()
        if (ready.get("provider") != "gemini" or ready.get("model") != approval["model"]
                or ready.get("validation_retries") != 0 or ready.get("call_cap") != 2
                or ready.get("calls_remaining") != 1):
            raise RuntimeError("Gemini readiness differs from approved Cross-Service state")

        live = client.get(f"http://127.0.0.1:8015/context/trace/{trace}",
                          params={"mode": "cross_service"}).raise_for_status().json()
        prepared = prepare(live, query, ready["input_budget"])
        prepared_sha = hashlib.sha256(prepared.payload.encode("ascii")).hexdigest()
        if (prepared_sha != source["projected_payload_sha256"] or prepared.redacted
                or prepared.omitted or live["event_count"] != 5
                or live["completeness_status"] != "PARTIAL"):
            raise RuntimeError("Live Context differs from approved Cross-Service input")

        started_at = datetime.now(timezone.utc).isoformat()
        write_new(ATTEMPT, {
            "approval_id": approval["approval_id"], "mode": "cross_service",
            "started_at_utc": started_at,
            "input_sha256": prepared_sha, "status": "STARTED",
        })
        response = client.post("http://127.0.0.1:8016/analyze/trace", json=request,
                               headers={"X-Required-Provider": "gemini"})
        body = response.json()
        remaining_response = client.get("http://127.0.0.1:8016/ready")
        remaining_body = remaining_response.json()
        exhausted = (remaining_response.status_code == 503 and
                     remaining_body.get("error", {}).get("code") == "PROVIDER_CALL_BUDGET_EXHAUSTED")
        remaining = 0 if exhausted else remaining_body.get("calls_remaining")
        passed = response.status_code == 200 and remaining == 0
        if passed:
            try:
                analysis = IncidentAnalysis.model_validate(body)
            except ValidationError:
                passed = False
            else:
                passed = (analysis.provider == "gemini" and analysis.trace_id == trace
                          and analysis.analysis_mode == "cross_service"
                          and analysis.input_event_ids == live["evidence_event_ids"])
        status = "PASS" if passed else ("INVALID_RESPONSE" if response.status_code == 200 else "FAILED")
        record = {
            "approval_id": approval["approval_id"], "mode": "cross_service",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "http_status": response.status_code, "status": status,
            "response": body if response.status_code == 200 else {"error": body.get("error")},
        }
        if status != "PASS":
            record["raw_capture"] = copy_one_raw_response(approval["approval_id"], "cross_service", ROOT)
            record["diagnostic"] = capture_smoke_diagnostic(started_at)
        write_new(RESULT, record)
        print(json.dumps({"status": status, "http_status": response.status_code,
                          "analysis_status": body.get("analysis_status"),
                          "provider": body.get("provider"), "calls_remaining": remaining,
                          "error_code": body.get("error", {}).get("code")}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    finally:
        stop_llm()
