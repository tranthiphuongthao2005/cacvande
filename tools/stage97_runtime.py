"""Approval-gated Stage 9.7 runtime actions and sanitized trace evidence collection."""

import argparse
import base64
import json
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from tools.stage97_preflight import (
    BUILDS, PLAN_DIR, PORTS, PROJECT, READER_KEYS, ROOT, SERVICES, GateError, approval, check, command,
    compose, digest, external, local_daemon, plan_hash, read_env, resources, static,
)

WORKERS = ["incident-management", "context-integration", "workflow-dispatcher", "monitoring-worker"]
DATA_SERVICES = ["elasticsearch", "user-db", "product-db", "order-db"]
APPS = ["user-service", "product-service", "order-service", "filebeat", "detection-service",
        "context-service", "mock-analysis", "workflow-n8n"]
FAULTS = {
    "E2E-02": ("order-service", "processing", 500),
    "E2E-03": ("product-service", "delay", 504),
    "E2E-04": ("order-service", "database", 503),
    "E2E-05": ("product-service", "unavailable", 502),
}
EVIDENCE_FIELDS = ("event_id", "trace_id", "service_name", "message", "status_code", "error_type",
                   "dependency_service", "request_id", "span_id", "@timestamp")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def local_client(service, **kwargs):
    return httpx.Client(base_url=f"http://127.0.0.1:{PORTS[service]}", trust_env=False,
                        follow_redirects=False, **kwargs)


def artifact(directory, name, data):
    path = external(directory)
    path.mkdir(parents=True, exist_ok=True)
    with (path / name).open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")


def live_integrity():
    command([sys.executable, "-B", "-m", "tools.check_stage_9_1_integrity"], timeout=35)


def assert_owned():
    local_daemon()
    ids = command(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={PROJECT}"]).split()
    for identity in ids:
        value = command(["docker", "inspect", identity, "--format",
                         '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}|'
                         '{{ index .Config.Labels "com.docker.compose.service" }}']).strip()
        worktree, _, service = value.rpartition("|")
        check(Path(worktree).resolve() == ROOT and service in SERVICES, "PROJECT_OWNERSHIP_UNVERIFIED")


def resources_gate():
    info = resources()
    check(not info["busy_stage97_ports"] and not any(info["stage97_objects"].values()), "PROJECT_OR_PORT_OCCUPIED")
    check(info["host_free_memory_bytes"] >= 2 * 2**30 and info["docker_memory_bytes"] >= 5 * 2**30
          and info["docker_cpu"] >= 4 and info["disk_free_bytes"] >= 10 * 2**30, "INSUFFICIENT_RESOURCE_HEADROOM")
    # Read-only measurement is a planning threshold, not saturation/load evidence.


def up(services, values, *, timeout=150, extra=()):
    compose(["up", "-d", "--no-build", "--pull", "never", *extra, *services], values=values, timeout=timeout)


def exec_python(service, code, args, values):
    text = compose(["exec", "-T", service, "python", "-B", "-c", code, *args], values=values, timeout=15)
    return json.loads(text)


def provision_keys(env_file, values):
    check(all(values[key] == "STAGE97_PENDING" for key in READER_KEYS), "ES_KEYS_ALREADY_SET")
    check(bool(compose(["ps", "-q", "elasticsearch"], values=values).strip()), "OWNED_ES_REQUIRED")
    with local_client("elasticsearch", timeout=8, auth=("elastic", values["ELASTIC_PASSWORD"])) as client:
        for key in sorted(READER_KEYS):
            response = client.post("/_security/api_key", json={
                "name": f"{PROJECT}-{key.lower()}", "expiration": "7d",
                "role_descriptors": {"trace_reader": {"indices": [{"names": ["thesis-logs-*"],
                                                                 "privileges": ["read"]}]}},
            })
            response.raise_for_status()
            values[key] = response.json()["encoded"]
    # The external file must already be protected by the operator. Update atomically once all keys exist.
    temp = env_file.with_name(env_file.name + ".stage97.tmp")
    with temp.open("x", encoding="ascii") as stream:
        stream.writelines(f"{key}={value}\n" for key, value in values.items())
    os.replace(temp, env_file)


SCHEMA_COMMANDS = {
    "monitoring-worker": "from app.monitoring_store import MonitoringStore; "
                         "from app.monitoring_config import Settings; import time; MonitoringStore(Settings.from_env()).open(time.time())",
    "context-integration": "from app.context_integration import Settings; "
                           "from app.context_integration_store import ContextPackageStore; "
                           "ContextPackageStore(Settings.from_env()).install()",
    "workflow-dispatcher": "from app.workflow_config import Settings; from app.workflow_store import Store; "
                           "Store(Settings.from_env()).install()",
    "incident-management": "from app.incident_config import Settings; from app.incident_handoff import Source; "
                           "from app.incident_store import IncidentStore; s=Settings.from_env(); "
                           "IncidentStore(s.storage_path).install(); Source(s).install()",
}

PROBE_FIXTURE = """
import json,time
from datetime import datetime,timezone
from uuid import uuid4
from app.context_integration import Settings,utc
from app.context_integration_models import build_package,context_payload
from app.context_integration_store import Claim,ContextPackageStore
from app.context_store import Snapshot
from app.hybrid_detection import HybridRouter
from app.incident_context import build_context
from app.monitoring_models import make_event
from app.monitoring_store import Claim as DetectionClaim
from app.rule_detection import normalize
s=Settings(); store=ContextPackageStore(s)
trace,key,token=uuid4().hex,uuid4().hex,uuid4().hex
now=time.time()
raw={'trace_id':trace,'event_id':key,'@timestamp':datetime.now(timezone.utc).isoformat(),
     'service_name':'order','message':'request_completed','level':'ERROR','status_code':503,
     'span_id':'a'*16,'endpoint':'/orders','http_method':'POST'}
events={item.event_id:item.model_dump(mode='json') for item in normalize([raw],trace)[0]}
result=HybridRouter().route(trace,'AUTO',lambda _:Snapshot([raw]))[1]
event=make_event(result,DetectionClaim(trace,1,token,1,events),now)
with store.connection(write=True) as db:
    namespace=db.execute('SELECT namespace FROM context_settings WHERE id=1').fetchone()[0]
    db.execute("INSERT INTO context_jobs(event_id,trace_id,trace_version,document,state,attempts,token,lease_until,updated_at) "
               "VALUES(?,?,1,?,'FETCHING_CONTEXT',1,?,?,?)",
               (event.detection_event_id,trace,event.model_dump_json(),token,now+60,now))
claim=Claim(event.detection_event_id,trace,1,event.model_dump_json(),token,1,None)
context=context_payload(build_context(trace,'cross_service',None,Snapshot([raw])).model_dump(mode='json'),trace)
doc=build_package(event,context,claim,events,namespace,utc(now),utc(now))
assert store.finish(claim,now,package=doc)
print(json.dumps({'trace_id':trace,'package_id':doc.context_package_id,'context_sha256':doc.context_payload_sha256}))
"""

# This code only emits normalized durable metadata for a single exact package or trace.
PROBE_RESULT = """
import json,sqlite3,sys
db=sqlite3.connect('file:/data/monitoring.sqlite?mode=ro',uri=True)
db.row_factory=sqlite3.Row
row=db.execute('SELECT j.state,j.execution_id,j.signature,r.context_payload_sha256,r.response_sha256,'
               "json_extract(r.document,'$.analysis_provider') AS provider,"
               "json_extract(r.document,'$.is_mock') AS is_mock "
               'FROM workflow_jobs j LEFT JOIN workflow_results r ON r.job_id=j.job_id WHERE j.package_id=?',
               (sys.argv[1],)).fetchone()
attempt=db.execute("SELECT code FROM workflow_attempts WHERE package_id=? AND phase='WEBHOOK' ORDER BY id DESC LIMIT 1",
                   (sys.argv[1],)).fetchone()
print(json.dumps({**dict(row),'webhook_attempt':attempt[0] if attempt else None} if row else None))
"""


def workflow_probe(values, directory, approval_path, decision):
    check(decision.get("workflow_published_verified") is True and decision.get("synthetic_probe_allowed") is True,
          "SYNTHETIC_PROBE_NOT_APPROVED")
    statuses(values)
    claim_request(approval_path, decision, "synthetic-workflow-probe")
    code = PROBE_FIXTURE.replace("s=Settings();", "s=Settings(storage_path='/data/monitoring.sqlite');")
    fixture = exec_python("workflow-dispatcher", code, [], values)
    artifact(directory, "synthetic-workflow-probe-fixture.json", {"synthetic": True, **fixture})
    until = time.monotonic() + 90
    while time.monotonic() < until:
        observed = exec_python("workflow-dispatcher", PROBE_RESULT, [fixture["package_id"]], values)
        if observed and observed["state"] in {"COMPLETED", "NEEDS_REVIEW", "ANALYSIS_FAILED", "DISPATCH_FAILED"}:
            if observed["state"] != "COMPLETED" or observed["webhook_attempt"]:
                break
        time.sleep(2)
    else:
        raise GateError("N8N_PROBE_TIMEOUT")
    artifact(directory, "synthetic-workflow-probe-result.json", {
        "synthetic": True, **fixture, **observed, "test_plan_sha256": plan_hash(),
    })
    check(observed["state"] == "COMPLETED" and re.fullmatch(r"[0-9]{1,32}", observed["execution_id"] or "")
          and observed["provider"] == "mock" and observed["is_mock"] == 1
          and observed["context_payload_sha256"] == fixture["context_sha256"]
          and observed["webhook_attempt"] == "WEBHOOK_RESULT_NOT_COMMITTED", "N8N_PROBE_VERIFICATION_FAILED")
    print(json.dumps({"status": "SYNTHETIC_PROBE_VERIFIED", "workflow_execution_id": observed["execution_id"]}))


def schema(values):
    statuses(values, require_workers=False)
    end = time.monotonic() + 45
    with local_client("elasticsearch", timeout=5, auth=("elastic", values["ELASTIC_PASSWORD"])) as es:
        while es.head("/thesis-logs-*").status_code != 200:
            check(time.monotonic() < end, "NO_INDEX_BEFORE_MONITORING_FLOOR")
            time.sleep(2)
    for service, code in SCHEMA_COMMANDS.items():
        compose(["run", "--rm", "--no-deps", "--pull", "never", "--entrypoint", "python", service,
                 "-B", "-c", code], values=values, timeout=35)


def statuses(values, *, require_workers=True):
    result = {}
    # Compose v5 emits one JSON object per line; never expose full inspect output.
    output = compose(["ps", "--format", "json"], values=values)
    parsed = json.loads(output) if output.lstrip().startswith("[") else [json.loads(line) for line in output.splitlines()]
    states = {row["Service"]: (row["State"], row.get("Health")) for row in parsed}
    required = set(DATA_SERVICES + APPS + (WORKERS if require_workers else []))
    check(all(states.get(name, (None,))[0] == "running" for name in required), "REQUIRED_CONTAINER_NOT_RUNNING")
    check(all(states[name][1] == "healthy" for name in DATA_SERVICES + ["filebeat"]),
          "DB_OR_FILEBEAT_NOT_HEALTHY")
    result["running_services"] = sorted(required)
    for name in ("user-service", "product-service", "order-service", "context-service"):
        with local_client(name, timeout=5) as client:
            check(client.get("/health").status_code == 200 and client.get("/ready").status_code == 200,
                  "APP_OR_CONTEXT_NOT_READY")
    with local_client("detection-service", timeout=5) as client:
        ready = client.get("/ready")
        cap = client.get("/detect/capabilities").json()
        check(ready.status_code == 503 and ready.json()["error"]["code"] == "NOT_READY_FOR_SCORING"
              and cap["rule_based_available"] and cap["auto_available"] and not cap["mecolog_available"]
              and cap["mecolog_block_reason"] == "DOMAIN_NOT_VALIDATED", "DETECTION_GUARD_MISMATCH")
    if require_workers:
        checks = {
            "monitoring-worker": "from app.monitoring_store import MonitoringStore; "
                                 "from app.monitoring_config import Settings; import time,json; "
                                 "print(json.dumps(MonitoringStore(Settings.from_env()).read_status(time.time())))",
            "context-integration": "from app.context_integration_store import ContextPackageStore; "
                                   "from app.context_integration import Settings; import time,json; "
                                   "print(json.dumps(ContextPackageStore(Settings.from_env()).inspect(time.time())))",
            "workflow-dispatcher": "from app.workflow_store import Store; from app.workflow_config import Settings; "
                                   "import time,json; print(json.dumps(Store(Settings.from_env()).inspect(time.time())))",
        }
        for service, code in checks.items():
            check(exec_python(service, code, [], values)["ready"], "WORKER_NOT_READY")
        with local_client("incident-management", timeout=5) as client:
            check(client.get("/ready").status_code == 200 and client.get("/incidents").status_code == 401
                  and client.get("/incidents", headers=bearer(values)).status_code == 200, "INCIDENT_AUTH_OR_NOT_READY")
    with local_client("workflow-n8n", timeout=5) as client:
        check(client.get("/healthz/readiness").status_code == 200, "N8N_NOT_READY")
    mock_check = ('import json,urllib.request; url="http://mock-analysis:8000/health"; '
                  'print(json.dumps(json.load(urllib.request.urlopen(url, timeout=4))))')
    check(exec_python("mock-analysis", mock_check, [], values)["is_mock"] is True, "MOCK_ANALYSIS_NOT_READY")
    result["n8n_functional_execution"] = "NOT_PROVEN_BY_READINESS"
    result["mecolog"] = "NOT_READY_FOR_SCORING"
    return result


def bearer(values):
    return {"Authorization": "Bearer " + values["INCIDENT_API_TOKEN"]}


def no_fault(values):
    code = ('import os,json; print(json.dumps({"enabled":os.getenv("LAB_ENABLED")=="1",'
            '"has_fault":bool(os.getenv("LAB_FAULT"))}))')
    for name in ("product-service", "order-service"):
        check(not any(exec_python(name, code, [], values).values()), "ACTIVE_FAULT_DETECTED")


def post_once(client, path, payload):
    started = time.perf_counter()
    response = client.post(path, json=payload)
    return response, round((time.perf_counter() - started) * 1000, 3)


def wait_http(service, path, until):
    with local_client(service, timeout=2) as client:
        while time.monotonic() < until:
            try:
                if client.get(path).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(.25)
    raise GateError("SERVICE_READINESS_DEADLINE")


def fixture(values):
    with local_client("user-service", timeout=8) as user, local_client("product-service", timeout=8) as product:
        u, _ = post_once(user, "/users", {"name": "Stage97", "email": f"stage97-{uuid4().hex}@example.com"})
        p, _ = post_once(product, "/products", {"name": "Stage97", "price": "12.50"})
        check(u.status_code == p.status_code == 201, "FIXTURE_SEED_FAILED")
    return {"user_id": u.json()["id"], "product_id": p.json()["id"], "quantity": 1}


def claim_request(approval_path, decision, case):
    prefix = external(approval_path).parent
    with (prefix / f"stage97-{decision['approval_id']}-{case}.used").open("x", encoding="utf-8") as stream:
        json.dump({"approval_id": decision["approval_id"], "case": case, "claimed_at": now_iso()}, stream)


def get_detection(trace, values):
    code = ('import json, sqlite3, sys; db=sqlite3.connect("file:/data/monitoring.sqlite?mode=ro",uri=True); '
            'trace=sys.argv[1]; row=db.execute("SELECT document FROM results WHERE trace_id=? '
            'ORDER BY trace_version DESC LIMIT 1",(trace,)).fetchone(); '
            'print(json.dumps(json.loads(row[0]) if row else None))')
    return exec_python("monitoring-worker", code, [trace], values)


def elastic_events(trace, values):
    with local_client("elasticsearch", timeout=8, auth=("elastic", values["ELASTIC_PASSWORD"])) as es:
        response = es.post("/thesis-logs-*/_search", json={
            "size": 513, "query": {"term": {"trace_id": trace}}, "_source": list(EVIDENCE_FIELDS),
        })
        response.raise_for_status()
        hits = response.json()["hits"]["hits"]
        check(len(hits) < 513, "EVIDENCE_SEARCH_LIMIT")
        return [{"id": row["_id"], "index": row["_index"], "event": row["_source"]} for row in hits]


def log_events(trace, values):
    selected = {}
    disk = ('import glob,json,sys; trace=sys.argv[1]; found=[]; '
            'records=(json.loads(line) for path in glob.glob("/var/log/thesis/*.jsonl*") '
            'for line in open(path,encoding="utf-8")); '
            'print(json.dumps([r for r in records if r.get("trace_id")==trace]))')
    fields = {"event_id", "trace_id", "event", "service", "timestamp", "status", "code", "dependency", "request_id", "span_id"}
    for service in ("user-service", "product-service", "order-service"):
        file = exec_python(service, disk, [trace], values)
        stream = compose(["logs", "--no-color", "--no-log-prefix", "--tail", "2000", service], values=values)
        decoded = []
        for line in stream.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("trace_id") == trace and row.get("event_id"):
                decoded.append(row)
        selected[service] = {"producer_file": [{k: v for k, v in row.items() if k in fields} for row in file],
                             "docker_log": [{k: v for k, v in row.items() if k in fields} for row in decoded]}
    return selected


def persistence(trace, values):
    code = """import json,sqlite3,sys
trace=sys.argv[1]
db=sqlite3.connect('file:/data/monitoring.sqlite?mode=ro',uri=True)
views={}
tables={
'context':('context_jobs','trace_id','event_id,state,last_error'),
'packages':('context_packages','trace_id',"package_id,trace_version,json_extract(document,'$.context_payload_sha256'),json_extract(document,'$.context_completeness')"),
'workflows':('workflow_jobs','trace_id','job_id,execution_id,state,error_code,dispatched_at,accepted_at,analysis_started_at,analysis_completed_at,signature'),
'results':('workflow_results','trace_id',"job_id,context_payload_sha256,response_sha256,validation_status,json_extract(document,'$.analysis_provider'),json_extract(document,'$.is_mock')")
}
for key,(table,col,fields) in tables.items():
    views[key]=db.execute(f'SELECT {fields} FROM {table} WHERE {col}=?',(trace,)).fetchall()
views['monitoring_time']=db.execute('SELECT first_seen,last_seen,last_detection_at FROM traces WHERE trace_id=?',(trace,)).fetchall()
views['context_latency']=db.execute('SELECT a.attempted_at,a.retrieval_ms,a.processing_ms FROM context_attempts a JOIN context_jobs j ON a.event_id=j.event_id WHERE j.trace_id=?',(trace,)).fetchall()
views['workflow_latency']=db.execute('SELECT a.phase,a.code,a.latency_ms FROM workflow_attempts a JOIN workflow_jobs j ON a.package_id=j.package_id WHERE j.trace_id=?',(trace,)).fetchall()
views['monitoring_sqlite_allocated_bytes']=db.execute('PRAGMA page_size').fetchone()[0]*db.execute('PRAGMA page_count').fetchone()[0]
print(json.dumps(views))
"""
    return exec_python("monitoring-worker", code, [trace], values)


def incident_evidence(trace, values):
    with local_client("incident-management", timeout=8) as api:
        response = api.get("/incidents", params={"trace_id": trace}, headers=bearer(values))
        response.raise_for_status()
        found = response.json()
        check(found["total"] <= 1, "DUPLICATE_INCIDENT")
        if not found["items"]:
            return {}
        incident, = found["items"]
        identity = incident["incident_id"]
        extra = {}
        for kind in ("timeline", "evidence", "revisions", "history"):
            item = api.get(f"/incidents/{identity}/{kind}", headers=bearer(values), params={"limit": 100})
            item.raise_for_status()
            extra[kind] = item.json()["items"]
        return {"incident": incident, **extra}


def collect(trace, values):
    check(re.fullmatch("[0-9a-f]{32}", trace) and trace != "0" * 32, "REAL_TRACE_ID_REQUIRED")
    return {"trace_id": trace, "detected": get_detection(trace, values), "elasticsearch": elastic_events(trace, values),
            "logs": log_events(trace, values), "incident": incident_evidence(trace, values),
            "durable_states": persistence(trace, values), "collected_at": now_iso()}


def verify_normal_events(evidence):
    sources = []
    for key in ("producer_file", "docker_log"):
        unique = {}
        for log in evidence["logs"].values():
            for row in log[key]:
                check(unique.setdefault(row["event_id"], row) == row, "CONFLICTING_SOURCE_EVENT")
        sources.append(unique)
    hits = {}
    for item in evidence["elasticsearch"]:
        row = item["event"]
        check(item["id"] == row.get("event_id") and item["id"] not in hits, "DUPLICATE_OR_WRONG_ES_ID")
        hits[item["id"]] = row
    check(sources[0] == sources[1] and bool(hits) and sources[0].keys() == hits.keys(),
          "EVENT_ID_JOIN_MISMATCH")
    fields = {"service": "service_name", "event": "message", "status": "status_code", "code": "error_type",
              "dependency": "dependency_service", "request_id": "request_id", "span_id": "span_id",
              "trace_id": "trace_id"}
    for event_id, row in sources[0].items():
        es = hits[event_id]
        check(all(row.get(key) == es.get(value) for key, value in fields.items())
              and datetime.fromisoformat(row["timestamp"]) == datetime.fromisoformat(es["@timestamp"]),
              "EVENT_PAYLOAD_CONFLICT")
    return hits


def normal(values, directory, approval_path, decision):
    statuses(values)
    no_fault(values)
    probe = json.loads((external(directory) / "synthetic-workflow-probe-result.json").read_text())
    check(probe["synthetic"] is True and probe["state"] == "COMPLETED" and probe["test_plan_sha256"] == plan_hash()
          and probe["webhook_attempt"] == "WEBHOOK_RESULT_NOT_COMMITTED"
          and re.fullmatch(r"[0-9]{1,32}", probe["execution_id"]), "N8N_PROBE_EVIDENCE_REQUIRED")
    approval(approval_path, "normal")
    claim_request(approval_path, decision, "E2E-01")
    payload = fixture(values)
    with local_client("order-service", timeout=10) as client:
        response, latency = post_once(client, "/orders", payload)
    trace = response.headers.get("x-trace-id", "")
    artifact(directory, "E2E-01-request.json", {"trace_id": trace, "http_status": response.status_code,
                                               "latency_ms": latency, "recorded_at": now_iso()})
    check(response.status_code == 201 and re.fullmatch("[0-9a-f]{32}", trace), "NORMAL_BUSINESS_REQUEST_FAILED")
    deadline = time.monotonic() + 120
    detected = None
    while time.monotonic() < deadline:
        found = get_detection(trace, values)
        if found and found["detection_id"] == (detected or {}).get("detection_id"):
            break
        detected = found
        time.sleep(10)  # Stabilization across two reads and at least two default poll intervals.
    else:
        raise GateError("NORMAL_MONITORING_RESULT_NOT_STABLE")
    evidence = collect(trace, values)
    artifact(directory, "E2E-01-trace-evidence.json", evidence)
    es = verify_normal_events(evidence)
    confirmed = {"order", "product", "user"} <= {row["service_name"] for row in es.values()}
    state = evidence["detected"]
    check(confirmed and es.keys() <= set(state["worker_observed_event_ids"])
          and state["detection_status"] == "NO_ANOMALY_DETECTED" and state["requested_mode"] == "AUTO"
          and state["executed_mode"] == "RULE_BASED" and state["detection_source"] == "rule_based"
          and state["fallback_reason"] == "DOMAIN_NOT_VALIDATED" and state["model_score"] is None
          and state["matched_rules"] == [] and not evidence["incident"]
          and all(not evidence["durable_states"][key] for key in ("packages", "workflows", "results")),
          "NORMAL_END_TO_END_ACCEPTANCE_FAILED")
    artifact(directory, "E2E-01-acceptance.json", {
        "case": "E2E-01", "status": "PASS", "trace_id": trace, "test_plan_sha256": plan_hash(),
        "evidence_sha256": digest(external(directory) / "E2E-01-trace-evidence.json"), "verified_at": now_iso(),
    })
    print(json.dumps({"case": "E2E-01", "status": "PASS", "trace_id": trace}))


def approved_fault(values, directory, approval_path, decision, case):
    check(case in FAULTS and decision.get("case_id") == case, "FAULT_CASE_NOT_APPROVED_OR_SUPPORTED")
    check(decision.get("normal_case_passed") is True and decision.get("rollback_observer") and
          decision.get("max_activation_seconds") == 90, "FAULT_ROLLBACK_APPROVAL_REQUIRED")
    normal_path = external(decision["normal_acceptance_path"])
    normal_result = json.loads(normal_path.read_text())
    check(digest(normal_path) == decision.get("normal_acceptance_sha256")
          and normal_result.get("status") == "PASS" and normal_result.get("case") == "E2E-01"
          and normal_result.get("test_plan_sha256") == plan_hash(), "NORMAL_PASS_EVIDENCE_REQUIRED")
    statuses(values)
    no_fault(values)
    service, fault, expected = FAULTS[case]
    label = "ORDER" if service == "order-service" else "PRODUCT"
    active = {**values, f"STAGE97_{label}_LAB_ENABLED": "1", f"STAGE97_{label}_FAULT": fault}
    static(active, fault=(service, fault))
    check(approval(approval_path, "fault") == decision, "APPROVAL_CHANGED")
    expiry = datetime.fromisoformat(decision["expires_at"])
    check((expiry - datetime.now(timezone.utc)).total_seconds() >= 90, "FAULT_APPROVAL_WINDOW_TOO_SHORT")
    claim_request(approval_path, decision, case)
    payload = fixture(values)
    check((expiry - datetime.now(timezone.utc)).total_seconds() >= 90, "FAULT_APPROVAL_WINDOW_TOO_SHORT")
    trace = None
    result = {"case": case, "rollback": "ROLLBACK_FAILED"}
    start = time.monotonic()
    try:
        # Allow time for rollback inside the 90-second activation budget.
        up([service], active, timeout=35, extra=("--no-deps", "--force-recreate"))
        wait_http(service, "/health", start + 42)
        check(time.monotonic() - start < 42, "FAULT_ACTIVATION_BUDGET_EXHAUSTED")
        with local_client("order-service", timeout=8) as order:
            response, latency = post_once(order, "/orders", payload)
        trace = response.headers.get("x-trace-id")
        result.update(trace_id=trace, http_status=response.status_code, latency_ms=latency)
        check(response.status_code == expected and trace, "FAULT_BUSINESS_OUTCOME_MISMATCH")
    finally:
        try:
            up([service], values, timeout=30, extra=("--no-deps", "--force-recreate"))
            no_fault(values)
            wait_http(service, "/ready", start + 90)
            check(time.monotonic() - start <= 90, "ROLLBACK_DEADLINE_EXCEEDED")
            result["rollback"] = "VERIFIED"
        finally:
            artifact(directory, f"{case}-request-and-rollback.json", result)
    # A business status and rollback are not an E2E acceptance verdict.
    print(json.dumps({"case": case, "trace_id": trace, "status": "EVIDENCE_COLLECTION_REQUIRED"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "build", "infra", "keys", "services", "schema", "workers",
                                          "readiness", "workflow-probe", "normal", "fault", "collect", "postgres",
                                          "stop"))
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--env-file")
    parser.add_argument("--approval")
    parser.add_argument("--artifact-dir")
    parser.add_argument("--case")
    parser.add_argument("--trace")
    parser.add_argument("--resources", action="store_true")
    args = parser.parse_args()
    try:
        check(Path(args.worktree).resolve() == ROOT and args.project == PROJECT, "WRONG_WORKTREE_OR_PROJECT")
        if args.action == "preflight":
            values = read_env(PLAN_DIR / "stage97.env.example")
            result = {"static": static(values), "test_plan_sha256": plan_hash()}
            if args.resources:
                result["resources"] = resources()
            print(json.dumps(result, indent=2))
            return 0

        check(args.approval and args.env_file, "APPROVAL_AND_EXTERNAL_ENV_REQUIRED")
        action = args.action
        decision = approval(args.approval, "readiness" if action == "collect" else action)
        path = external(args.env_file)
        values = read_env(path, live=True, allow_pending=action in {"build", "infra", "keys", "stop"})
        live_integrity()
        static(values)
        assert_owned()
        if action == "build":
            resources_gate()
            compose(["build", *sorted(BUILDS)], values=values, timeout=720)
        elif action == "infra":
            resources_gate()
            up(DATA_SERVICES, values)
        elif action == "keys":
            provision_keys(path, values)
        elif action == "services":
            up([*APPS, "logging-files", "logging-setup"], values)
        elif action == "schema":
            schema(values)
        elif action == "workers":
            check(decision.get("workflow_published_verified") is True, "VERIFY_N8N_PRODUCTION_PUBLICATION_FIRST")
            statuses(values, require_workers=False)
            no_fault(values)
            up(WORKERS, values)
        elif action == "readiness":
            no_fault(values)
            print(json.dumps(statuses(values), indent=2))
        elif action in {"workflow-probe", "normal", "fault", "collect"}:
            check(args.artifact_dir, "EXTERNAL_ARTIFACT_DIRECTORY_REQUIRED")
            if action == "normal":
                normal(values, args.artifact_dir, args.approval, decision)
            elif action == "workflow-probe":
                workflow_probe(values, args.artifact_dir, args.approval, decision)
            elif action == "fault":
                approved_fault(values, args.artifact_dir, args.approval, decision, args.case)
            else:
                artifact(args.artifact_dir, f"trace-{args.trace}-evidence.json", collect(args.trace or "", values))
        elif action == "postgres":
            postgres(values)
        elif action == "stop":
            compose(["stop", *sorted(SERVICES)], values=values, timeout=360)
        return 0
    except GateError as failure:
        print(json.dumps({"status": "BLOCKED", "code": str(failure)}))
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError, httpx.HTTPError):
        print(json.dumps({"status": "BLOCKED", "code": "COMMAND_CONFIG_OR_RUNTIME_FAILURE"}))
    return 1


def postgres(values):
    # Dedicated test runner uses the isolated user-db and deletes only its generated test databases.
    check(bool(compose(["ps", "-q", "user-db"], values=values).strip()), "OWNED_TEST_DB_REQUIRED")
    output = compose(["run", "--rm", "--no-deps", "--pull", "never", "stage97-pg-tests"],
                     values=values, timeout=240)
    summary = re.findall(r"(?m)^10 passed[^\r\n]*", output)
    check(len(summary) == 1 and "skipped" not in summary[0], "POSTGRES_TEST_COUNT_MISMATCH")
    print(summary[0])


if __name__ == "__main__":
    raise SystemExit(main())
