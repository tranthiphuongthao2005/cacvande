"""Verify the production n8n webhook through the scenario-only mock workflow."""

import argparse
import json
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import httpx

from tools.audit_research import audit

ROOT = Path(__file__).resolve().parents[1]
WEBHOOK = "http://127.0.0.1:5678/webhook/scenario-incident"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trace-id", default="09b71700f5dca84ec31f133b92b2ba91")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    env = dict(row.split("=", 1) for row in (ROOT / ".env.n8n").read_text().splitlines())
    headers = {"Authorization": "Bearer " + env["WORKFLOW_TRIGGER_TOKEN"]}
    payload = {"trace_id": args.trace_id, "analysis_mode": "cross_service", "request_id": uuid4().hex}
    with httpx.Client(timeout=62, trust_env=False) as client:
        assert client.get("http://127.0.0.1:5678/healthz/readiness").status_code == 200
        assert client.get("http://127.0.0.1:8016/ready").json()["provider"] == "mock"
        deadline = monotonic() + 45
        while True:
            unauthorized = client.post(WEBHOOK, json=payload)
            if unauthorized.status_code != 404 or monotonic() >= deadline:
                break
            sleep(2)
        assert unauthorized.status_code == 401 and unauthorized.json()["error"]["code"] == "UNAUTHORIZED_TRIGGER"
        wrong = client.post(WEBHOOK, json=payload, headers={"Authorization": "Bearer wrong"})
        assert wrong.status_code == 401
        invalid = client.post(WEBHOOK, json={**payload, "ground_truth": "private-fixture"}, headers=headers)
        assert invalid.status_code == 422 and "private-fixture" not in invalid.text
        result = client.post(WEBHOOK, json=payload, headers=headers).raise_for_status().json()
        assert not result["replayed"] and result["analysis_status"] == "INSUFFICIENT_EVIDENCE"
        assert result["provider_type"] == "mock" and result["context_completeness"] == "PARTIAL"
        assert result["review_required"] and result["notification_status"] == "SUPPRESSED"
        assert result["context_calls"] == result["llm_calls"] == 1
        assert len(result["report"]["evidence_event_ids"]) == 5
        replay = client.post(WEBHOOK, json=payload, headers=headers).raise_for_status().json()
        assert replay == {**result, "replayed": True}
        conflicting = client.post(WEBHOOK, json={**payload, "analysis_mode": "single_service",
                                  "service_name": "order"}, headers=headers)
        assert conflicting.status_code == 409
        detection = client.get("http://127.0.0.1:8014/ready")
        assert detection.status_code == 503 and detection.json()["error"]["code"] == "NOT_READY_FOR_SCORING"
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({"request": payload, "incident": result, "replay_reused_incident": True,
                   "webhook_auth_status": [unauthorized.status_code, wrong.status_code],
                   "invalid_payload_status": invalid.status_code, "conflict_status": conflicting.status_code,
                   "detection": detection.json(), "research_audit": audit()}, stream, indent=2)
    print(f"Verified one persistent incident and replay via n8n. Artifact: {args.output}")


if __name__ == "__main__":
    main()
