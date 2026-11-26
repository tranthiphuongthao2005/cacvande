import copy
import json
import re
import subprocess
from datetime import datetime, timezone

import pytest

from app.context_integration import Settings as ContextSettings
from app.context_integration_store import ContextPackageStore
from app.monitoring_config import Settings as MonitoringSettings
from app.monitoring_store import MonitoringStore
from app.workflow_config import Settings as WorkflowSettings
from app.workflow_store import Store
from tools import stage97_preflight as preflight
from tools import stage97_runtime as runtime


@pytest.fixture(scope="module")
def config():
    template = preflight.PLAN_DIR / "stage97.env.example"
    source = preflight.compose(["config", "--format", "json"], values=preflight.read_env(template))
    return json.loads(source)


def test_actual_merged_compose_has_expected_scope(config):
    preflight.audit_config(config)
    assert "kibana" not in config["services"] and "llm-service" not in config["services"]
    assert "n8n" not in config["services"]
    assert all(not spec.get("external") for spec in config["volumes"].values())
    assert not config["services"]["stage97-pg-tests"].get("ports")


@pytest.mark.parametrize("violation", ["socket", "host_port", "external_network", "shared_volume",
                                       "wrong_context_path", "provider", "service", "filebeat_read_write",
                                       "fault", "container_name", "host_network"])
def test_merged_configuration_fails_closed(config, violation):
    candidate = copy.deepcopy(config)
    services = candidate["services"]
    if violation == "socket":
        services["filebeat"]["volumes"].append({"type": "bind", "source": "/var/run/docker.sock", "target": "/sock"})
    if violation == "host_port":
        services["elasticsearch"]["ports"][0]["host_ip"] = "0.0.0.0"
    if violation == "external_network":
        candidate["networks"]["logging"]["external"] = True
    if violation == "shared_volume":
        candidate["volumes"]["monitoring-data"]["name"] = "unrelated-shared"
    if violation == "wrong_context_path":
        services["context-integration"]["environment"]["CONTEXT_INTEGRATION_URL"] = "http://host.docker.internal"
    if violation == "provider":
        services["mock-analysis"]["environment"]["WORKFLOW_EXTERNAL_ALLOWED"] = "true"
    if violation == "service":
        services["llm-service"] = {}
    if violation == "filebeat_read_write":
        next(v for v in services["filebeat"]["volumes"] if v["source"] == "order-logs")["read_only"] = False
    if violation == "fault":
        services["product-service"]["environment"]["LAB_ENABLED"] = "1"
    if violation == "container_name":
        services["user-service"]["container_name"] = "shared"
    if violation == "host_network":
        services["workflow-n8n"]["network_mode"] = "host"
    with pytest.raises(preflight.GateError):
        preflight.audit_config(candidate)


def test_operator_gate_requires_a_signed_off_scoped_phase(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "plan_hash", lambda: "approved-digest")
    path = tmp_path / "approval.json"
    baseline = dict(approved=True, project=preflight.PROJECT, worktree=str(preflight.ROOT), phase="9.7B",
                    test_plan_sha256="approved-digest", operator="operator", approval_id="isolated-smoke",
                    expires_at="2040-01-01T00:00:00+00:00", max_order_requests=1, actions=["normal"])
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    path.write_text(json.dumps(baseline))
    assert preflight.approval(path, "normal", now)["max_order_requests"] == 1
    for update in ({"approved": False}, {"actions": ["normal", "fault"]}, {"project": "other"},
                   {"max_order_requests": 2}, {"test_plan_sha256": "different"},
                   {"expires_at": "2020-01-01T00:00:00+00:00"}):
        path.write_text(json.dumps({**baseline, **update}))
        with pytest.raises(preflight.GateError):
            preflight.approval(path, "normal", now)


def test_env_template_cannot_be_used_live():
    template = preflight.PLAN_DIR / "stage97.env.example"
    assert preflight.read_env(template)["CONTEXT_ES_API_KEY"] == "STAGE97_PENDING"
    with pytest.raises(preflight.GateError, match="CREDENTIALS"):
        preflight.read_env(template, live=True, allow_pending=True)


def test_order_request_claim_cannot_be_replayed(tmp_path):
    path = tmp_path / "approval.json"
    decision = {"approval_id": "once-only"}
    runtime.claim_request(path, decision, "E2E-01")
    with pytest.raises(FileExistsError):
        runtime.claim_request(path, decision, "E2E-01")


def test_event_join_checks_identity_and_shared_payload():
    event = {"event_id": "a" * 32, "trace_id": "b" * 32, "service": "order", "event": "request_completed",
             "status": 201, "timestamp": "2026-11-26T10:00:00Z"}
    indexed = {"event_id": event["event_id"], "trace_id": event["trace_id"], "service_name": "order",
               "message": "request_completed", "status_code": 201, "@timestamp": "2026-11-26T10:00:00+00:00"}
    sample = {"logs": {"order": {"producer_file": [event], "docker_log": [event]}},
              "elasticsearch": [{"id": event["event_id"], "event": indexed}]}
    assert runtime.verify_normal_events(sample).keys() == {event["event_id"]}
    indexed["status_code"] = 503
    with pytest.raises(preflight.GateError, match="PAYLOAD_CONFLICT"):
        runtime.verify_normal_events(sample)


def test_injected_readonly_evidence_snippets_compile(monkeypatch):
    def verify(_service, code, _args, _values):
        compile(code, "<isolated-command>", "exec")
        return None
    monkeypatch.setattr(runtime, "exec_python", verify)
    runtime.get_detection("a" * 32, {})
    runtime.persistence("a" * 32, {})
    for code in [runtime.PROBE_FIXTURE, runtime.PROBE_RESULT, *runtime.SCHEMA_COMMANDS.values()]:
        compile(code, "<isolated-command>", "exec")


def test_synthetic_probe_creates_only_a_workflow_fixture(tmp_path, capsys):
    path = str(tmp_path / "monitoring.sqlite")
    MonitoringStore(MonitoringSettings(storage_path=path)).open(1700000000)
    ContextPackageStore(ContextSettings(storage_path=path, namespace=preflight.PROJECT)).install()
    workflow = Store(WorkflowSettings(storage_path=path))
    workflow.install()
    code = runtime.PROBE_FIXTURE.replace("s=Settings();", f"s=Settings(storage_path={path!r});")
    exec(compile(code, "<synthetic-fixture>", "exec"), {})
    fixture = json.loads(capsys.readouterr().out)
    assert re.fullmatch("[0-9a-f]{64}", fixture["context_sha256"])
    with workflow.connect() as db:
        assert db.execute("SELECT state FROM workflow_jobs").fetchone()[0] == "PENDING_DISPATCH"
        assert db.execute("SELECT count(*) FROM results").fetchone()[0] == 0


def test_plan_freeze_and_case_denominators():
    assert re.fullmatch("[0-9a-f]{64}", preflight.plan_hash())
    manifest = json.loads((preflight.PLAN_DIR / "test_case_manifest.json").read_text())
    assert [case["id"] for case in manifest["cases"]] == [f"E2E-{i:02}" for i in range(1, 16)]
    assert manifest["execution_status"] == "NOT_EXECUTED"
    assert set(runtime.FAULTS) == {"E2E-02", "E2E-03", "E2E-04", "E2E-05"}
