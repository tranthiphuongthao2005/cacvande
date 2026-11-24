"""Approved configuration shapes and observed-evidence checks for the shared collector."""
import subprocess
from dataclasses import dataclass
from datetime import datetime
from time import monotonic, sleep


@dataclass(frozen=True)
class Adapter:
    configuration: str
    scenario: str | None
    mechanism: str
    handling: str
    campaign: str


ADAPTERS = {item.configuration: item for item in (
    Adapter("normal-a", None, "normal", "none", "normal-a"),
    Adapter("processing-a", "processing", "processing_failure", "local", "processing-a-development-pilot"),
    Adapter("timeout-a", "timeout", "dependency_timeout", "propagated", "timeout-a-development-acceptance"),
    Adapter("database-a", "database", "database_connection_failure", "local", "database-a-development-acceptance"),
    Adapter("cascade-a", "cascade", "dependency_unavailable", "propagated", "cascade-a-development-acceptance"),
)}


def runtime_fault_db_health(timeout):
    result = subprocess.run(["docker", "inspect", "--format", "{{.State.Health.Status}}",
                             "thesis-log-anomaly-order-db-1"],
                            check=True, capture_output=True, text=True, timeout=timeout)
    if result.stdout.strip() != "healthy":
        raise ValueError("Order DB is not independently healthy")
    return "healthy"


def verify_timeouts(runtime):
    order = float(runtime["order"][3])
    product = float(runtime["product"][3])
    if order != 2.0 or product != 2.0:
        raise ValueError("Timeout A requires Order deadline 2.0 s and Product delay 2.25 s")


def product_completed_late(events):
    completions = {(row["service"], row.get("status")): datetime.fromisoformat(row["timestamp"])
                   for row in events if row.get("event") == "request_completed"}
    order, product = completions.get(("order", 504)), completions.get(("product", 200))
    return order is not None and product is not None and product > order


def await_timeout_trace(fetch, deadline, *, clock=monotonic, wait=sleep):
    """Do not seal before the downstream Product server has completed."""
    while clock() < deadline:
        events = fetch(min(20, deadline - clock()))
        if product_completed_late(events) and any(
            span.get("kind") == "SpanKind.SERVER" and span.get("end_time")
            and span.get("resource", {}).get("attributes", {}).get("service.name") == "product"
            for span in events
        ):
            return events
        remaining = deadline - clock()
        if remaining > 0:
            wait(min(.25, remaining))
    raise TimeoutError("Late Product completion not observed before capture deadline")


def verify_observed(adapter, detail):
    events = detail["docker_events"]
    spans = detail["spans"]
    roots = [s for s in spans if s["kind"] == "SpanKind.SERVER" and s["parent_id"] is None]
    if len(roots) != 1 or roots[0]["service"] != "order" or not roots[0]["end_time"]:
        raise ValueError("Expected one closed Order SERVER root")
    client_ids = {s["span_id"] for s in spans if s["kind"] == "SpanKind.CLIENT"
                  and s["service"] == "order" and s["parent_id"] == roots[0]["span_id"]}
    dependencies = [s for s in spans if s["kind"] == "SpanKind.SERVER" and s["parent_id"] in client_ids
                    and s["end_time"]]
    if len(client_ids) != 2 or len(dependencies) != 2 or {s["service"] for s in dependencies} != {"user", "product"}:
        raise ValueError("Expected linked User and Product dependency calls")
    completions = {(e["service"], e.get("status")) for e in events if e.get("event") == "request_completed"}
    expected_product = 503 if adapter.scenario == "cascade" else 200
    if not {("user", 200), ("product", expected_product)} <= completions:
        raise ValueError("Unexpected dependency responses")
    if adapter.scenario == "timeout" and not product_completed_late(events):
        raise ValueError("Timeout A missing late Product completion")
    if adapter.scenario == "cascade" and not any(
        e.get("service") == "order" and e.get("event") == "dependency_attempt_failed"
        and e.get("dependency") == "product" and e.get("code") == "dependency_unavailable" for e in events
    ):
        raise ValueError("Cascade A missing Product-to-Order propagation evidence")
