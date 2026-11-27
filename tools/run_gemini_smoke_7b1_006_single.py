"""Run one approved Gemini Single-Service smoke attempt and record its outcome."""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pydantic import ValidationError

from app.llm_analysis import AnalysisRequest, IncidentAnalysis, prepare


ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "experiments/gemini_smoke_7b1"
APPROVAL = SMOKE / "gemini-smoke-7b1-006.json"
ACTIVATION = SMOKE / "gemini-smoke-7b1-006.activation.json"
ATTEMPT = SMOKE / "gemini-smoke-7b1-006.single.attempt.json"
RESULT = SMOKE / "gemini-smoke-7b1-006.single.result.json"
COMPOSE = (
    "docker", "compose", "--env-file", ".env.elk", "--env-file", ".env.context",
    "--env-file", ".env.detection", "-f", "compose.yaml", "-f", "compose.logging.yaml",
    "-f", "compose.context.yaml", "-f", "compose.detection.yaml", "-f", "compose.llm.yaml",
)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def stop_llm():
    completed = subprocess.run((*COMPOSE, "stop", "llm-service"), cwd=ROOT, check=False)
    if completed.returncode:
        print("LLM cleanup needs manual verification")


def main():
    approval = read(APPROVAL)
    activation = read(ACTIVATION)
    if ATTEMPT.exists() or RESULT.exists():
        raise RuntimeError("Single-Service attempt already exists")
    if approval["approval_id"] != activation["approval_id"] or approval["trace_id"] != activation["trace_id"]:
        raise RuntimeError("Approval and activation differ")
    expires = datetime.fromisoformat(activation["expires_at_utc"])
    if datetime.now(timezone.utc) >= expires:
        raise RuntimeError("Smoke activation expired")

    source = approval["inputs"]["single_service"]
    source_path = ROOT / source["path"]
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != source["sha256"]:
        raise RuntimeError("Approved Context snapshot changed")

    trace = approval["trace_id"]
    query = AnalysisRequest(trace_id=trace, mode="single_service", service_name="order")
    request = {"trace_id": trace, "mode": "single_service", "service_name": "order"}
    with httpx.Client(timeout=30, trust_env=False) as client:
        ready = client.get("http://127.0.0.1:8016/ready").raise_for_status().json()
        if (ready.get("provider") != "gemini" or ready.get("model") != approval["model"]
                or ready.get("validation_retries") != 0 or ready.get("call_cap") != 2
                or ready.get("calls_remaining") != 2):
            raise RuntimeError("Gemini readiness differs from approved start state")

        live = client.get(f"http://127.0.0.1:8015/context/trace/{trace}",
                          params={"mode": "single_service", "service_name": "order"}).raise_for_status().json()
        prepared = prepare(live, query, ready["input_budget"])
        prepared_sha = hashlib.sha256(prepared.payload.encode("ascii")).hexdigest()
        if (prepared_sha != source["projected_payload_sha256"] or prepared.redacted
                or prepared.omitted or live["event_count"] != 3 or live["completeness_status"] != "UNKNOWN"):
            raise RuntimeError("Live Context differs from approved Single-Service input")

        write_new(ATTEMPT, {
            "approval_id": approval["approval_id"], "mode": "single_service",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "input_sha256": prepared_sha, "status": "STARTED",
        })
        response = client.post("http://127.0.0.1:8016/analyze/trace", json=request,
                               headers={"X-Required-Provider": "gemini"})
        body = response.json()
        remaining = client.get("http://127.0.0.1:8016/ready").json().get("calls_remaining")
        passed = response.status_code == 200 and remaining == 1
        if passed:
            try:
                analysis = IncidentAnalysis.model_validate(body)
            except ValidationError:
                passed = False
            else:
                passed = (analysis.provider == "gemini" and analysis.trace_id == trace
                          and analysis.analysis_mode == "single_service"
                          and analysis.input_event_ids == live["evidence_event_ids"])
        status = "PASS" if passed else ("INVALID_RESPONSE" if response.status_code == 200 else "FAILED")
        record = {
            "approval_id": approval["approval_id"], "mode": "single_service",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "http_status": response.status_code, "status": status,
            "response": body if response.status_code == 200 else {"error": body.get("error")},
        }
        write_new(RESULT, record)
        print(json.dumps({"status": status, "http_status": response.status_code,
                          "analysis_status": body.get("analysis_status"),
                          "provider": body.get("provider"), "calls_remaining": remaining,
                          "error_code": body.get("error", {}).get("code")}, ensure_ascii=False))
        if status != "PASS":
            stop_llm()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        stop_llm()
        raise
