"""Collect fresh local lab runs; keep observation and label files separate."""

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from random import Random
from uuid import uuid4

import httpx

from app.micro_dataset import canonical, checksum
from app.trace_store import TraceStore
from experiments.run_scenario import ROOT, SETUPS, URLS, compose, compose_command, read_trace, wait_ready


def write(path, data):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical(data) + "\n")


def await_snapshot(store, trace, expected):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        session = store.fetch(trace)
        if session:
            seen = {event.event_id for event in session.events}
            if seen == expected:
                return session
            if seen - expected:
                raise ValueError("Elasticsearch returned additional events for trace")
        time.sleep(.5)
    raise ValueError("Elasticsearch and Docker event IDs did not converge")


def collect(root, repetitions, seed, select, *, on_run=None, deadline=None):
    if root.exists():
        raise FileExistsError(root)
    env = {**os.environ, "LAB_WITH_ELK": "1"}
    credentials = dict(row.split("=", 1) for row in (ROOT / ".env.detection").read_text().splitlines())
    oracle = {row["scenario_id"]: row for row in json.loads((ROOT / "experiments/ground_truth.json").read_text())}
    rng = Random(seed)
    root.mkdir(parents=True, exist_ok=False)
    for name in ("observations", "labels", "rejected"):
        (root / name).mkdir()
    committed = []
    families = {"retry": "product-unavailable", "cascade": "product-unavailable",
                "unavailable": "product-unavailable"}
    with httpx.Client(timeout=15, trust_env=False) as api, httpx.Client(
        base_url="http://127.0.0.1:9200", timeout=20, trust_env=False,
        headers={"Authorization": f"ApiKey {credentials['DETECTION_ES_API_KEY']}"},
    ) as es:
        store = TraceStore(es)
        wait_ready(api)
        for scenario in select:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Collection deadline reached before the next scenario")
            product, order, attempts = SETUPS[scenario]
            target = oracle[scenario]["expected_behavior"]
            # Fixtures are real DB writes through normal app endpoints before faults start.
            requests = []
            for _ in range(repetitions):
                run = uuid4().hex
                payload = {"quantity": rng.randint(1, 7)}
                creations = [("user", "/users", {"name": "Lab customer", "email": f"{run}@example.com"}),
                             ("product", "/products", {"name": "Lab product", "price": f"{rng.randint(5, 90)}.25"})]
                if rng.randrange(2):
                    creations.reverse()
                for service, route, body in creations:
                    result = api.post(URLS[service] + route, json=body)
                    result.raise_for_status()
                    payload[f"{service}_id"] = result.json()["id"]
                requests.append((run, payload, rng.uniform(.04, .32), [service for service, _, _ in creations]))
            local = {**env, "PRODUCT_LAB_FAULT": product, "ORDER_LAB_FAULT": order,
                     "LAB_ATTEMPTS": str(attempts), "DATASET_PRODUCT_TIMEOUT": str(rng.choice([2.15, 2.35, 2.55]))}
            try:
                command = compose_command(local, faults=True)
                if product == "delay":
                    command += ["-f", "compose.dataset-latency.yaml"]
                subprocess.run(command + ["up", "-d", "--no-deps", "product-service", "order-service"],
                               cwd=ROOT, env=local, check=True, timeout=120)
                ready_until = time.monotonic() + 35
                while time.monotonic() < ready_until:
                    try:
                        if all(api.get(url + "/health").is_success for url in URLS.values()):
                            break
                    except httpx.RequestError:
                        pass
                    time.sleep(.5)
                else:
                    raise RuntimeError("Fault containers not live")
                for run, payload, pause, creation_order in requests:
                    if deadline is not None and time.monotonic() >= deadline:
                        raise TimeoutError("Collection deadline reached before the next measured request")
                    time.sleep(pause)
                    started = datetime.now(timezone.utc).isoformat()
                    if target["request_service"] == "product":
                        response = api.get(URLS["product"] + "/products/" + payload["product_id"])
                    else:
                        response = api.post(URLS["order"] + "/orders", json=payload)
                    trace = response.headers.get("x-trace-id")
                    error = response.json().get("error", {}).get("code")
                    if scenario == "timeout":
                        time.sleep(2)
                    telemetry = read_trace(env, trace)
                    raw = [e for e in telemetry if "event_id" in e]
                    failures = sum(e.get("event") == "dependency_attempt_failed" for e in raw)
                    valid = response.status_code == target["status"] and error == target.get("error")
                    valid &= "attempts" not in target or failures == target["attempts"]
                    if scenario in {"normal", "cascade", "timeout", "retry"}:
                        valid &= {e["service"] for e in raw} == {"user", "product", "order"}
                    record = {"run_id": run, "trace_id": trace, "scenario_id": scenario, "timestamp": started,
                              "family": families.get(scenario, scenario), "fault_type": scenario,
                              "label": int(scenario != "normal"), "observed_status": response.status_code,
                              "observed_error": error, "provenance": "lab-injection+http+docker-events-v1",
                              "product_delay_base": local["DATASET_PRODUCT_TIMEOUT"] if product == "delay" else None}
                    if on_run is not None:
                        on_run(record, telemetry, valid, target, {
                            "product_fault": product, "order_fault": order, "attempts": attempts,
                            "product_delay_base": record["product_delay_base"],
                            "response_wait_seconds": 2 if scenario == "timeout" else 0,
                        }, {
                            "quantity": payload["quantity"], "creation_order": creation_order,
                            "pause_seconds": round(pause, 4), "entry_service": target["request_service"],
                            "concurrency": 1,
                        })
                    if not valid or not raw or len(raw) != len({e["event_id"] for e in raw}):
                        write(root / "rejected" / f"{run}.json", record)
                        continue
                    session = await_snapshot(store, trace, {e["event_id"] for e in raw})
                    observation = session.model_dump(mode="json")
                    write(root / "observations" / f"{run}.json", observation)
                    write(root / "labels" / f"{run}.json", record)
                    committed.append({"run_id": run, "observation_sha256": checksum(observation),
                                      "label_sha256": checksum(record)})
            finally:
                if on_run is None:
                    compose(env, "up", "-d", "--no-deps", "product-service", "order-service")
                else:
                    subprocess.run(compose_command(env) + [
                        "up", "-d", "--no-deps", "product-service", "order-service"
                    ], cwd=ROOT, env=env, check=True, timeout=120)
                wait_ready(api)
    write(root / "collection.json", {"seed": seed, "scenarios_requested": select,
                                     "repetitions": repetitions, "runs": committed})


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--repetitions", type=int, default=2, choices=range(2, 21), metavar="2..20")
    cli.add_argument("--seed", type=int, default=123)
    cli.add_argument("--scenario", choices=SETUPS, action="append")
    args = cli.parse_args()
    collect(args.output, args.repetitions, args.seed, list(dict.fromkeys(args.scenario or SETUPS)))


if __name__ == "__main__":
    main()
