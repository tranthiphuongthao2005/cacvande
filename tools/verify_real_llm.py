"""Explicitly authorized two-call smoke against a fresh local OpenAI-backed service."""

import argparse
import json
import os
from pathlib import Path
from time import perf_counter

import httpx

from app.llm_analysis import AnalysisRequest, IncidentAnalysis, ModelAnalysis, prepare, validate_model
from app.trace_store import valid_trace

LLM = "http://127.0.0.1:8016"
CONTEXT = "http://127.0.0.1:8015"
REPORT_METADATA = set(IncidentAnalysis.model_fields) - set(ModelAnalysis.model_fields)


def config_ok(ready):
    return (ready.get("provider") == "openai" and bool(ready.get("model")) and
            ready.get("call_cap") == ready.get("calls_remaining") == 2 and
            ready.get("validation_retries") == 0 and ready.get("max_output_tokens") == 1200 and
            ready.get("decoding") == "model_defaults" and isinstance(ready.get("input_budget"), int))


def smoke(client, trace, save):
    ready = client.get(LLM + "/ready").raise_for_status().json()
    if not config_ok(ready) or ready["model"] != os.environ["LLM_MODEL"].strip():
        raise ValueError("Expected a fresh OpenAI service with exactly two calls and zero retries")
    queries = [
        AnalysisRequest(trace_id=trace, mode="single_service", service_name="order"),
        AnalysisRequest(trace_id=trace, mode="cross_service"),
    ]
    prepared = []
    for query in queries:
        params = {"mode": query.mode}
        if query.service_name:
            params["service_name"] = query.service_name
        context = client.get(f"{CONTEXT}/context/trace/{trace}", params=params).raise_for_status().json()
        prepared.append(prepare(context, query, ready["input_budget"]))
    if not prepared[0].events or not set(prepared[0].events) < set(prepared[1].events) or any(p.omitted for p in prepared):
        raise ValueError("Expected nonempty matched contexts without truncation")
    observed = {(row["service_name"], row["status_code"]) for row in prepared[1].events.values()
                if row["message"] == "request_completed"}
    if not {("user", 200), ("product", 503), ("order", 502)} <= observed or not any(
        row["service_name"] == "order" and row["dependency_service"] == "product"
        and row["message"] == "dependency_attempt_failed" for row in prepared[1].events.values()
    ):
        raise ValueError("Trace does not match the verified cascade pattern")
    identities = set()
    for query, source in zip(queries, prepared):
        started = perf_counter()
        metadata = {"trace_id": trace, "analysis_mode": query.mode,
                    "configured_model": ready["model"], "prompt_version": ready["prompt_version"]}
        try:
            reply = client.post(LLM + "/analyze/trace", json=query.model_dump(mode="json"))
        except httpx.HTTPError:
            save({**metadata, "provider_response_status": "UNKNOWN_TRANSPORT",
                  "round_trip_ms": round((perf_counter() - started) * 1000, 3)})
            return False
        metadata.update({"http_status": reply.status_code, "round_trip_ms": round((perf_counter() - started) * 1000, 3)})
        if reply.status_code != 200:
            detail = reply.json().get("error", {}).get("code")
            save({**metadata, "provider_response_status": "NO_ACCEPTED_RESPONSE",
                  "error": detail if isinstance(detail, str) and detail.isupper() and detail.isidentifier() else None})
            return False
        try:
            report = IncidentAnalysis.model_validate(reply.json())
            if (report.trace_id != trace or report.analysis_mode != query.mode or report.provider != "openai" or
                    report.selected_service != query.service_name or list(source.events) != report.input_event_ids or
                    report.configured_model != ready["model"] or report.prompt_version != ready["prompt_version"] or
                    report.context_completeness != source.completeness or report.provider_response_status != "completed"):
                raise ValueError("Report differs from verified configuration or evidence scope")
            _, warnings = validate_model(report.model_dump(include=set(IncidentAnalysis.model_fields)
                                                         - REPORT_METADATA), source)
            if (not any(line.strip() for line in report.recommended_checks) or
                    not any(line.strip() for line in report.limitations) or
                    report.analysis_status == "ANALYZED" and report.suspected_root_cause is None or
                    not set(warnings) <= set(report.validation_warnings)):
                raise ValueError("Required report content or warnings missing")
        except (ValueError, TypeError, KeyError):
            save({**metadata, "provider_response_status": "REJECTED_REPORT",
                  "evidence_validation": "FAILED"})
            return False
        identities.add(report.model_name)
        save({**metadata, "analysis_id": report.analysis_id, "model_name": report.model_name,
              "provider_response_status": report.provider_response_status, "latency_ms": report.processing_time_ms,
              "token_usage": report.token_usage, "estimated_cost": report.estimated_cost,
              "analysis_status": report.analysis_status, "evidence_validation": report.validation_status,
              "warnings": warnings, "input_event_ids": report.input_event_ids,
              "context_completeness": report.context_completeness, "semantic_review": "PENDING"})
    return len(identities) == 1


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--trace-id", default="09b71700f5dca84ec31f133b92b2ba91")
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--approve-api-cost", action="store_true")
    args = cli.parse_args()
    if not all(os.getenv(key, "").strip() for key in ("OPENAI_API_KEY", "LLM_MODEL")):
        cli.exit(2, "BLOCKED_MISSING_CREDENTIALS\n")
    if not args.approve_api_cost or os.getenv("LLM_ALLOW_EXTERNAL") != "1":
        cli.exit(2, "BLOCKED_COST_NOT_APPROVED\n")
    if not valid_trace(args.trace_id):
        cli.error("Invalid trace ID")
    with args.output.open("x", encoding="utf-8") as stream, httpx.Client(timeout=30, trust_env=False) as client:
        def save(row):
            stream.write(json.dumps(row, ensure_ascii=True, allow_nan=False) + "\n")
            stream.flush()

        try:
            passed = smoke(client, args.trace_id, save)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            save({"status": "PREFLIGHT_OR_PROTOCOL_FAILED"})
            passed = False
    if not passed:
        cli.exit(1, "Smoke stopped. Inspect sanitized output before considering another run.\n")
    print("Two scoped responses passed structural verification. Semantic review remains pending.")


if __name__ == "__main__":
    main()
