"""Route one telemetry snapshot without enabling a new production scoring path."""

from dataclasses import dataclass
from time import perf_counter
from typing import Literal

import httpx
from pydantic import ConfigDict, Field, FiniteFloat

from app.contracts import StrictRecord, TraceId
from app.context_store import Snapshot
from app.rule_detection import DetectionResult, detect, normalize, result

ROUTER_VERSION = "1.0.0"
Mode = Literal["AUTO", "RULE_BASED", "MECOLOG_ONLY"]
FallbackReason = Literal[
    "MODEL_NOT_READY", "DOMAIN_NOT_VALIDATED", "INPUT_INCOMPATIBLE",
    "MODEL_RUNTIME_UNAVAILABLE", "MODEL_TIMEOUT", "MODEL_EXECUTION_ERROR",
]


class ModelReadiness(StrictRecord):
    checkpoint_available: bool | None = None
    runtime_available: bool | None = False
    configuration_compatible: bool | None = None
    input_compatible: bool | None = None
    domain_validated: bool | None = False
    approved_runtime_available: bool = False

    def blocker(self):
        if self.domain_validated is not True:
            return "DOMAIN_NOT_VALIDATED"
        if not self.approved_runtime_available:
            return "MODEL_NOT_READY"
        if self.runtime_available is not True:
            return "MODEL_RUNTIME_UNAVAILABLE"
        if self.checkpoint_available is not True or self.configuration_compatible is not True:
            return "MODEL_NOT_READY"
        return None


class DetectionError(StrictRecord):
    code: str


class HybridResult(DetectionResult):
    detection_source: Literal["rule_based", "mecolog", "none"]
    rule_version: str | None
    model_score: FiniteFloat | None = None
    requested_mode: Mode
    executed_mode: Literal["RULE_BASED", "MECOLOG_ONLY"] | None = None
    fallback_used: bool = False
    fallback_reason: FallbackReason | None = None
    model_readiness: ModelReadiness | None = None
    error: DetectionError | None = None
    router_version: Literal["1.0.0"] = ROUTER_VERSION


class ModelDecision(StrictRecord):
    """Expected decision from an approved snapshot-aware scoring adapter."""

    model_config = ConfigDict(strict=True)

    is_anomaly: bool
    model_score: FiniteFloat
    evidence_event_ids: list[TraceId] = Field(min_length=1)


class SnapshotFailure(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status, self.code = status, code


def read_snapshot(store, trace_id):
    if store is None:
        raise SnapshotFailure(503, "TRACE_STORE_NOT_CONFIGURED")
    try:
        snapshot = store.snapshot(trace_id)
        if snapshot.timed_out:
            raise SnapshotFailure(504, "INCOMPLETE_SEARCH")
        return snapshot
    except httpx.TimeoutException:
        raise SnapshotFailure(504, "ELASTICSEARCH_TIMEOUT") from None
    except httpx.HTTPError:
        raise SnapshotFailure(503, "TRACE_STORE_UNAVAILABLE") from None
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SnapshotFailure(502, "INVALID_SEARCH_RESPONSE") from None


@dataclass
class RoutingState:
    trace_id: str
    mode: Mode
    started: float
    readiness: ModelReadiness | None
    blocked: FallbackReason | None = None

    def wrap(self, detection, executed=None, error=None, score=None):
        data = detection.model_dump()
        if executed != "RULE_BASED":
            data.update(detection_source="mecolog" if score is not None else "none",
                        rule_version=None, model_score=score)
        return HybridResult(
            **data, requested_mode=self.mode, executed_mode=executed,
            fallback_used=self.mode == "AUTO" and self.blocked is not None,
            fallback_reason=self.blocked if self.mode == "AUTO" else None,
            model_readiness=self.readiness, error=DetectionError(code=error) if error else None,
        )

    def failure(self, status, code, executed=None):
        diagnostics = [code]
        if self.mode == "MECOLOG_ONLY" and self.blocked and self.blocked != code:
            diagnostics.append(self.blocked)
        return status, self.wrap(result(self.trace_id, self.started, "DETECTION_ERROR", diagnostics=diagnostics),
                                 executed, code)


class HybridRouter:
    def __init__(self, *, model=None, readiness=None, rule_engine=detect):
        self.model = model
        self.readiness = readiness or ModelReadiness()
        self.rule_engine = rule_engine

    def blocker(self):
        return self.readiness.blocker() or ("MODEL_RUNTIME_UNAVAILABLE" if self.model is None else None)

    def route(self, trace_id, mode, load_snapshot, started=None):
        state = RoutingState(trace_id, mode, perf_counter() if started is None else started,
                             None if mode == "RULE_BASED" else self.readiness)
        if mode != "RULE_BASED":
            state.blocked = self.blocker()
        if mode == "MECOLOG_ONLY" and state.blocked:
            return state.failure(503, "NOT_READY_FOR_SCORING")

        rule_selected = mode == "RULE_BASED" or state.blocked is not None
        try:
            snapshot = load_snapshot(trace_id)
        except SnapshotFailure as exc:
            return state.failure(exc.status, exc.code)

        if not rule_selected:
            status, output = self.score(state, snapshot)
            if status == 200 or mode == "MECOLOG_ONLY":
                return status, output
        try:
            return 200, state.wrap(self.rule_engine(trace_id, snapshot, state.started), "RULE_BASED")
        except Exception:
            return state.failure(500, "RULE_EXECUTION_ERROR", "RULE_BASED")

    def score(self, state: RoutingState, snapshot: Snapshot):
        try:
            events, invalid, conflicts = normalize(snapshot.rows, state.trace_id)
            compatible = bool(events and not (invalid or conflicts or snapshot.truncated)
                              and self.model.compatible(tuple(events)))
            state.readiness = self.readiness.model_copy(update={"input_compatible": compatible})
            if not compatible:
                state.blocked = "INPUT_INCOMPATIBLE"
                return state.failure(422, "SESSION_NOT_ELIGIBLE_FOR_SCORING")
            score = ModelDecision.model_validate(self.model.detect(tuple(events)))
            ids = set(score.evidence_event_ids)
            if not ids <= {event.event_id for event in events}:
                raise ValueError("Unverified evidence")
        except (TimeoutError, httpx.TimeoutException):
            state.blocked = "MODEL_TIMEOUT"
            return state.failure(504, "MODEL_TIMEOUT", "MECOLOG_ONLY")
        except (OSError, ImportError):
            state.blocked = "MODEL_RUNTIME_UNAVAILABLE"
            return state.failure(503, "SCORING_DEPENDENCY_UNAVAILABLE", "MECOLOG_ONLY")
        except Exception:
            state.blocked = "MODEL_EXECUTION_ERROR"
            return state.failure(503, "SCORING_DEPENDENCY_UNAVAILABLE", "MECOLOG_ONLY")

        detection = result(
            state.trace_id, state.started, "ANOMALY" if score.is_anomaly else "NO_ANOMALY_DETECTED",
            evidence_event_ids=sorted(ids), context_completeness="partial",
            observed_services=sorted({event.service_name for event in events}),
        )
        return 200, state.wrap(detection, "MECOLOG_ONLY", score=score.model_score)

    def deadline(self, trace_id, mode, started):
        state = RoutingState(trace_id, mode, started, None if mode == "RULE_BASED" else self.readiness)
        if mode == "AUTO":
            state.blocked = self.blocker()
        return state.failure(504, "DETECTION_TIMEOUT")
