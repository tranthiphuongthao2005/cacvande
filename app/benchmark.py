"""Offline benchmark validation and human-review aggregation."""

import json
import re
from collections import Counter, defaultdict
from itertools import groupby
from pathlib import Path
from random import Random
from statistics import mean, median
from typing import Literal

from pydantic import Field

from app.contracts import StrictRecord, TraceId
from app.incident_context import IncidentContext, Service
from app.llm_analysis import AnalysisRequest, prepare
from app.micro_dataset import checksum

MODES = ("single_service", "cross_service")
FORBIDDEN = {"ground_truth", "expected_root_cause", "injected_fault_type", "injected_fault",
             "root_cause_service", "root_cause_category", "scenario_id", "scenario_family",
             "annotation", "annotation_status", "acceptable_root_cause_variants",
             "expected_causal_chain", "expected_observations", "reviewer_id", "reviewer_role"}
SECRET = re.compile(r"(?i)\b(?:sk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._-]{8,})")


class GroundTruth(StrictRecord):
    run_id: str
    trace_id: TraceId
    scenario_family: str
    injected_fault: str | None
    injection_provenance: str
    root_cause_service: Service | None
    root_cause_category: str | None
    expected_causal_chain: list[str]
    affected_services: list[Service]
    supporting_event_ids: list[TraceId]
    expected_observations: list[str]
    acceptable_root_cause_variants: list[str]
    annotation_status: Literal["VERIFIED", "UNVERIFIED"]
    reviewer_id: str | None = None
    reviewer_role: str | None = None


class ClaimReview(StrictRecord):
    claim_id: str
    event_ids: list[TraceId]
    judgement: Literal["SUPPORTED", "UNSUPPORTED", "HALLUCINATED", "UNRATEABLE"]


class Review(StrictRecord):
    trace_id: TraceId
    mode: Literal["single_service", "cross_service"]
    provider_status: Literal["OK", "PROVIDER_FAILURE", "MISSING"]
    analysis_status: Literal["ANALYZED", "INSUFFICIENT_EVIDENCE"] | None
    reviewer_id: str
    adjudicated: bool
    model_name: str | None
    config_sha256: str | None
    input_event_ids: list[TraceId]
    cause_correct: bool | None
    service_correct: bool | None
    completeness_acknowledged: bool | None = None
    claims: list[ClaimReview]
    recommendations: list[bool | None]
    latency_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def isolate(value):
    if isinstance(value, dict):
        if FORBIDDEN & {key.lower() for key in value}:
            raise ValueError("Label fields in inference data")
        for item in value.values():
            isolate(item)
    elif isinstance(value, list):
        for item in value:
            isolate(item)
    elif isinstance(value, str) and (SECRET.search(value) or any(
            re.search(rf"\b{tag}\s*[:=]", value, re.I) for tag in FORBIDDEN)):
        raise ValueError("Sensitive or label content in inference data")


def read_checked(root, descriptor):
    if set(descriptor) != {"path", "sha256"}:
        raise ValueError("Unexpected artifact descriptor fields")
    path = (root / descriptor["path"]).resolve(strict=True)
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Artifact path outside benchmark")
    value = load(path)
    if checksum(value) != descriptor["sha256"]:
        raise ValueError("Artifact checksum mismatch")
    return value, path


def validate_context(raw, trace, mode, service):
    isolate(raw)
    snapshot = IncidentContext.model_validate(raw)
    if not snapshot.event_count:
        raise ValueError("Empty context snapshot")
    prepared = prepare(raw, AnalysisRequest(trace_id=trace, mode=mode, service_name=service), 16000)
    # Metadata outside the projection is never a source of causal labels.
    if prepared.redacted:
        raise ValueError("Unrecognized event text in frozen snapshot")
    return snapshot


def validate_manifest(path):
    manifest = load(path)
    if set(manifest) != {"protocol", "runs", "lock_sha256"}:
        raise ValueError("Unexpected manifest fields")
    if checksum({k: v for k, v in manifest.items() if k != "lock_sha256"}) != manifest["lock_sha256"]:
        raise ValueError("Manifest lock checksum mismatch")
    protocol = manifest["protocol"]
    required = {"protocol_id", "model", "prompt_version", "decoding", "rubric_version",
                "output_schema", "single_service", "reviewer_roles", "bootstrap_seed", "input_budget", "data_kind"}
    if (not required <= protocol.keys() or protocol["single_service"] != "order"
            or not all(protocol[k] for k in required - {"decoding", "bootstrap_seed"})):
        raise ValueError("Incomplete frozen protocol")
    if type(protocol["input_budget"]) is not int or not 256 <= protocol["input_budget"] <= 16000:
        raise ValueError("Invalid frozen evidence budget")
    if protocol["data_kind"] not in {"FIXTURE_ONLY", "HUMAN_REVIEW_INPUT"}:
        raise ValueError("Unknown benchmark data kind")
    scans, seen_trace, seen_run, seen_event, groups, paths = {}, set(), set(), set(), {}, set()
    for row in manifest["runs"]:
        run, trace, group, split = (row[key] for key in ("run_id", "trace_id", "group", "split"))
        if (not run or not group or trace in seen_trace or run in seen_run
                or split not in {"pilot", "development", "evaluation"}
                or type(row["previously_exposed"]) is not bool or split == "evaluation" and row["previously_exposed"]):
            raise ValueError("Invalid or exposed run")
        seen_trace.add(trace)
        seen_run.add(run)
        if groups.setdefault(group, split) != split:
            raise ValueError("Independence group crosses splits")
        contexts = {}
        for mode in MODES:
            value, file = read_checked(path.parent, row["contexts"][mode])
            if "labels" in file.relative_to(path.parent.resolve()).parts or file in paths:
                raise ValueError("Context/label storage isolation violation")
            paths.add(file)
            contexts[mode] = validate_context(value, trace, mode, "order" if mode == MODES[0] else None)
        single, cross = (contexts[mode] for mode in MODES)
        cross_by_id = {e.event_id: e for e in cross.events}
        if list(single.evidence_event_ids) != [e.event_id for e in cross.events if e.service_name == "order"]:
            raise ValueError("Single/Cross comparison scope mismatch")
        if any(event != cross_by_id[event.event_id] for event in single.events):
            raise ValueError("Event changed between the paired contexts")
        ids = set(cross_by_id)
        if seen_event & ids:
            raise ValueError("Event duplicated between traces")
        seen_event |= ids
        raw_truth, label_path = read_checked(path.parent, row["ground_truth"])
        if "labels" not in label_path.relative_to(path.parent.resolve()).parts or label_path in paths:
            raise ValueError("Ground truth must remain separate in labels/")
        paths.add(label_path)
        truth = GroundTruth.model_validate(raw_truth)
        if (truth.trace_id != trace or truth.run_id != run or not truth.injection_provenance.strip()
                or not set(truth.supporting_event_ids) <= ids
                or truth.annotation_status == "VERIFIED" and (
                    not (truth.reviewer_id or truth.reviewer_role) or not truth.supporting_event_ids
                    or not truth.root_cause_category or
                    truth.root_cause_category != "normal" and truth.root_cause_service is None)):
            raise ValueError("Unverified or invalid ground-truth lineage")
        # Exact normalized template signatures may not be assigned to separate groups.
        signatures = {checksum(sorted({(e.service_name, e.message) for e in cross.events})),
                      checksum([key for key, _ in groupby((e.service_name, e.message) for e in cross.events)])}
        campaign = row["campaign_id"]
        if not isinstance(campaign, str) or not campaign.strip():
            raise ValueError("Missing campaign provenance")
        campaign_key = ("campaign", campaign)
        if scans.setdefault(campaign_key, group) != group:
            raise ValueError("Campaign split across independent groups")
        for signature in signatures:
            key = ("signature", signature)
            if scans.setdefault(key, group) != group:
                raise ValueError("Template duplicate assigned to independent groups")
        scans[trace] = (row, truth, contexts)
    cases = {k: v for k, v in scans.items() if isinstance(k, str)}
    if not cases or not any(row["split"] == "evaluation" for row, _, _ in cases.values()):
        raise ValueError("No frozen evaluation traces")
    return protocol, cases


def validate_reviews(rows, cases, protocol):
    reviews = {}
    eligible = {trace for trace, (case, _, _) in cases.items() if case["split"] == "evaluation"}
    for raw in rows:
        row = Review.model_validate(raw)
        key = (row.trace_id, row.mode)
        if row.trace_id not in eligible or key in reviews or not row.adjudicated or not row.reviewer_id.strip():
            raise ValueError("Unexpected, duplicate or non-adjudicated review")
        _, label, contexts = cases[row.trace_id]
        scope = set(contexts[row.mode].evidence_event_ids)
        if len(set(row.input_event_ids)) != len(row.input_event_ids) or not set(row.input_event_ids) <= scope:
            raise ValueError("Invalid provider input scope")
        if row.provider_status == "OK":
            query = AnalysisRequest(trace_id=row.trace_id, mode=row.mode, service_name=contexts[row.mode].selected_service)
            expected = prepare(contexts[row.mode].model_dump(mode="json"), query, protocol["input_budget"])
            if (row.model_name != protocol["model"] or row.config_sha256 != checksum(protocol)
                    or row.input_event_ids != list(expected.events)):
                raise ValueError("Review does not match frozen configuration or input IDs")
        if len({c.claim_id for c in row.claims}) != len(row.claims):
            raise ValueError("Duplicate claim annotation")
        if any(c.judgement == "SUPPORTED" and (not c.event_ids or not set(c.event_ids) <= set(row.input_event_ids))
               for c in row.claims):
            raise ValueError("Supported claim requires valid citations")
        scorable = (row.provider_status == "OK" and row.analysis_status == "ANALYZED"
                    and label.annotation_status == "VERIFIED")
        if (not scorable and (row.cause_correct is not None or row.service_correct is not None)
                or row.provider_status != "OK" and (row.analysis_status or row.claims or row.recommendations)
                or row.provider_status == "OK" and (not row.analysis_status or not row.input_event_ids)
                or label.root_cause_service is None and row.service_correct is not None):
            raise ValueError("Outcome annotation conflicts with coverage or label")
        reviews[key] = row
    if set(reviews) != {(trace, mode) for trace in eligible for mode in MODES}:
        raise ValueError("Pair missing; record explicit MISSING rows")
    return reviews


def ratio(n, d):
    return {"numerator": n, "denominator": d, "value": n / d if d else None}


def summarize(rows):
    successful = [row for row in rows if row.provider_status == "OK"]
    causes = [r.cause_correct for r in successful if r.cause_correct is not None]
    services = [r.service_correct for r in successful if r.service_correct is not None]
    claims = [(row, claim) for row in successful for claim in row.claims]
    references = [(row, ref) for row, claim in claims for ref in claim.event_ids]
    verdicts = [claim.judgement for _, claim in claims if claim.judgement != "UNRATEABLE"]
    recommendations = [v for r in successful for v in r.recommendations if v is not None]
    result = {
        "root_cause_accuracy": ratio(sum(causes), len(causes)),
        "root_cause_service_accuracy": ratio(sum(services), len(services)),
        "evidence_reference_validity": ratio(sum(ref in r.input_event_ids for r, ref in references), len(references)),
        "evidence_support_rate": ratio(verdicts.count("SUPPORTED"), len(verdicts)),
        "unsupported_claim_rate": ratio(verdicts.count("UNSUPPORTED") + verdicts.count("HALLUCINATED"), len(verdicts)),
        "hallucination_rate": ratio(verdicts.count("HALLUCINATED"), len(verdicts)),
        "recommendation_relevance": ratio(sum(recommendations), len(recommendations)),
        "abstention_rate": ratio(sum(r.analysis_status == "INSUFFICIENT_EVIDENCE" for r in successful), len(successful)),
        "provider_coverage": ratio(len(successful), len(rows)),
        "provider_status_counts": dict(Counter(r.provider_status for r in rows)),
        "unrateable_claims": len(claims) - len(verdicts),
    }
    for name in ("latency_ms", "input_tokens", "output_tokens", "cost_usd"):
        values = [getattr(r, name) for r in successful if getattr(r, name) is not None]
        result[name] = {"n": len(values), "mean": mean(values) if values else None,
                        "median": median(values) if values else None}
    return result


def paired(protocol, cases, reviews):
    rows, strata = [], defaultdict(list)
    for trace, mode in sorted(reviews):
        if mode != MODES[0]:
            continue
        case, label, contexts = cases[trace]
        s, c = [reviews[trace, key] for key in MODES]
        entry = {"trace_id": trace, "group": case["group"], "family": label.scenario_family,
                 "single_completeness": contexts[MODES[0]].completeness_status,
                 "cross_completeness": contexts[MODES[1]].completeness_status,
                 "single_provider_status": s.provider_status, "cross_provider_status": c.provider_status}
        for field in ("cause_correct", "service_correct", "latency_ms", "input_tokens", "output_tokens", "cost_usd"):
            a, b = getattr(s, field), getattr(c, field)
            entry[field + "_delta"] = b - a if a is not None and b is not None else None
        rows.append(entry)
        strata[("fault_family", entry["family"])].append(entry)
        strata[("cross_completeness", entry["cross_completeness"])].append(entry)
    grouped = defaultdict(list)
    for row in rows:
        if (value := row["cause_correct_delta"]) is not None:
            grouped[row["group"]].append(value)
    delta = [x for values in grouped.values() for x in values]
    ci = None
    minimum = protocol.get("bootstrap_min_groups")
    if type(minimum) is int and minimum >= 2 and len(grouped) >= minimum:
        rng = Random(protocol["bootstrap_seed"])
        groups = [grouped[key] for key in sorted(grouped)]
        draws = sorted(mean(x for sample in rng.choices(groups, k=len(groups)) for x in sample) for _ in range(2000))
        ci = [draws[49], draws[1949]]
    return {
        "modes": {mode: summarize([r for r in reviews.values() if r.mode == mode]) for mode in MODES},
        "paired_rows": rows,
        "completeness": {mode: dict(Counter(cases[trace][2][mode].completeness_status
                                            for trace, key in reviews if key == mode)) for mode in MODES},
        "paired_cause_accuracy_delta": {"value": mean(delta) if delta else None,
                                        "scorable_pairs": len(delta), "independent_groups": len(grouped),
                                        "cluster_bootstrap_95": ci},
        "strata": [{"dimension": key[0], "value": key[1], "pairs": len(items),
                    "scorable_cause_pairs": len(values), "cause_delta": mean(values) if values else None}
                   for key, items in sorted(strata.items()) if
                   (values := [r["cause_correct_delta"] for r in items if r["cause_correct_delta"] is not None]) is not None],
    }
