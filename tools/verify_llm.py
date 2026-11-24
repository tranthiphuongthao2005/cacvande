"""Exercise a matched single/cross cascade pair against real Context, mock LLM only."""

import argparse
import json
from pathlib import Path

import httpx

from tools.audit_research import audit

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-id", default="09b71700f5dca84ec31f133b92b2ba91")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    with httpx.Client(timeout=15, trust_env=False) as client:
        llm = "http://127.0.0.1:8016"
        context = f"http://127.0.0.1:8015/context/trace/{args.trace_id}"
        ready = client.get(llm + "/ready").raise_for_status().json()
        if ready.get("provider") != "mock":
            raise ValueError("This verifier only runs with the mock provider")
        reports = {}
        for mode, fields in (("single_service", {"service_name": "order"}), ("cross_service", {})):
            request = {"mode": mode, **fields}
            source = client.get(context, params=request).raise_for_status().json()
            report = client.post(llm + "/analyze/trace", json={"trace_id": args.trace_id, **request}
                                 ).raise_for_status().json()
            assert report["provider"] == "mock" and report["token_usage"] is None and report["estimated_cost"] is None
            assert report["input_event_ids"] == source["evidence_event_ids"]
            assert report["analysis_status"] == "INSUFFICIENT_EVIDENCE"
            assert report == client.get(llm + "/analysis/" + report["analysis_id"]).raise_for_status().json()
            assert "CONTEXT_INCOMPLETE_DO_NOT_INFER_ABSENCE" in report["validation_warnings"]
            reports[mode] = report
        single, cross = reports.values()
        assert {o["service_name"] for o in single["observations"]} == {"order"}
        assert {o["service_name"] for o in cross["observations"]} == {"user", "product", "order"}
        assert set(single["input_event_ids"]) < set(cross["input_event_ids"])
        assert all(single[k] == cross[k] for k in ("model_name", "prompt_version", "analysis_config_id"))
        detection = client.get("http://127.0.0.1:8014/ready")
        assert detection.status_code == 503 and detection.json()["error"]["code"] == "NOT_READY_FOR_SCORING"
        invalid = client.post(llm + "/analyze/trace", json={"trace_id": args.trace_id, "ground_truth": "private"})
        assert invalid.status_code == 422 and "private" not in invalid.text
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({"trace_id": args.trace_id, "trigger": "scenario-triggered", "external_calls": 0,
                   "reports": reports, "detection_status": detection.json(), "research_audit": audit()}, stream, indent=2)
    print(f"Verified matched mock Single/Cross pair: {args.output}")


if __name__ == "__main__":
    main()
