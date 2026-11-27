"""Run one lab setup and preserve its ground truth in a separate run file."""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
SETUPS = {
    "normal": ("", "", 2),
    "timeout": ("delay", "", 1),
    "unavailable": ("unavailable", "", 1),
    "database": ("", "database", 1),
    "processing": ("", "processing", 1),
    "retry": ("unavailable", "", 3),
    "cascade": ("unavailable", "", 1),
}
URLS = {name: f"http://127.0.0.1:{8011+i}" for i, name in enumerate(("user", "product", "order"))}


def compose_command(environment, *, faults=False):
    command = ["docker", "compose", "-f", "compose.yaml"]
    if environment.get("LAB_WITH_ELK") == "1":
        command += ["--env-file", ".env.elk", "-f", "compose.logging.yaml"]
    if faults:
        command += ["-f", "compose.faults.yaml"]
    return command


def compose(environment, *args, faults=False):
    return subprocess.run([*compose_command(environment, faults=faults), *args],
                          cwd=ROOT, env=environment, check=True)


def wait_ready(client):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if all(client.get(url + "/ready").status_code == 200 for url in URLS.values()):
                return
        except httpx.RequestError:
            pass
        time.sleep(.5)
    raise RuntimeError("services did not become ready")


def read_trace(environment, trace_id, *, timeout=None):
    if not trace_id or len(trace_id) != 32 or any(c not in "0123456789abcdef" for c in trace_id):
        raise ValueError("Expected a valid response trace ID")
    logs = subprocess.run(
        [*compose_command(environment), "logs", "--no-log-prefix", "--no-color",
         "user-service", "product-service", "order-service"],
        cwd=ROOT, env=environment, check=True, capture_output=True, encoding="utf-8", timeout=timeout,
    )
    entries = []
    for line in (logs.stdout + "\n" + logs.stderr).splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and (
            row.get("trace_id") == trace_id or row.get("context", {}).get("trace_id") == "0x" + trace_id
        ):
            entries.append(row)
    if not entries:
        raise RuntimeError("No telemetry found for the request")
    return entries


def save_trace(environment, trace_id):
    entries = read_trace(environment, trace_id)
    target = ROOT / "experiments" / "telemetry"
    target.mkdir(exist_ok=True)
    with (target / f"{trace_id}.jsonl").open("x", encoding="utf-8") as stream:
        for row in entries:
            stream.write(json.dumps(row) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=SETUPS)
    parser.add_argument("--elk", action="store_true", help="keep the logging overlay active")
    args = parser.parse_args()
    truth = next(row for row in json.loads((ROOT/"experiments/ground_truth.json").read_text())
                 if row["scenario_id"] == args.scenario)
    product, order, attempts = SETUPS[args.scenario]
    env = {**os.environ, "PRODUCT_LAB_FAULT": product, "ORDER_LAB_FAULT": order,
           "LAB_ATTEMPTS": str(attempts), "LAB_WITH_ELK": "1" if args.elk else "0"}
    target = truth["expected_behavior"]
    run_id = uuid4().hex
    with httpx.Client(timeout=12 if args.elk else 5, trust_env=False) as client:
        compose(env, "up", "-d", "user-service", "product-service", "order-service")
        wait_ready(client)
        user = client.post(URLS["user"] + "/users", json={"name": "Lab user", "email": f"lab-{run_id}@example.com"})
        product_response = client.post(URLS["product"] + "/products", json={"name": "Lab item", "price": "5.25"})
        user.raise_for_status()
        product_response.raise_for_status()
        order_data = {"user_id": user.json()["id"], "product_id": product_response.json()["id"], "quantity": 1}
        try:
            compose(env, "up", "-d", "--no-deps", "--force-recreate", "product-service", "order-service", faults=True)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    if all(client.get(url + "/health").is_success for url in URLS.values()):
                        break
                except httpx.RequestError:
                    pass
                time.sleep(.5)
            else:
                raise RuntimeError("fault-mode services not healthy")
            if target["request_service"] == "product":
                response = client.get(URLS["product"] + f"/products/{order_data['product_id']}")
            else:
                response = client.post(URLS["order"] + "/orders", json=order_data)
            status = response.status_code
            error = response.json().get("error", {}).get("code")
            trace_id = response.headers.get("x-trace-id")
            if product == "delay":
                time.sleep(1.5 if args.elk else .6)  # Let the delayed request finish before recreation.
            save_trace(env, trace_id)
            run_dir = ROOT / "experiments" / "runs"
            run_dir.mkdir(exist_ok=True)
            with (run_dir / f"{run_id}.json").open("x", encoding="utf-8") as stream:
                json.dump({**truth, "observed": {"status": status, "error": error,
                            "trace_id": trace_id}}, stream, indent=2)
            if status != target["status"] or error != target.get("error"):
                raise SystemExit("Observed outcome differs from ground truth")
            print(f"Ground truth and observed trace saved to {run_dir / (run_id + '.json')}")
        finally:
            compose(env, "up", "-d", "--no-deps", "--force-recreate", "product-service", "order-service")
            wait_ready(client)


if __name__ == "__main__":
    main()
