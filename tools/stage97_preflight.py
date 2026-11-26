"""Stage 9.7A static audit and read-only Docker/Windows resource preflight."""

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN_DIR = ROOT / "experiments/system_e2e_9_7"
PROJECT = "thesis-e2e-stage97"
COMPOSE = (
    "compose.yaml", "compose.logging.yaml", "compose.detection.yaml", "compose.context.yaml",
    "compose.monitoring.yaml", "compose.context-integration.yaml", "compose.workflow.yaml",
    "compose.incident-management.yaml", "compose.e2e-stage97.yaml",
)
PROFILES = ("monitoring", "context-integration", "workflow-stage95", "incident-management", "postgres-tests")
PORTS = dict(zip(("user-service", "product-service", "order-service", "detection-service", "context-service",
                  "incident-management", "elasticsearch", "workflow-n8n"), (19011, 19012, 19013, 19014, 19015,
                                                                         19017, 19297, 15678), strict=True))
SERVICES = set(PORTS) | {
    "user-db", "product-db", "order-db", "monitoring-worker", "context-integration", "workflow-dispatcher",
    "mock-analysis", "filebeat", "logging-files", "logging-setup", "stage97-pg-tests",
}
BUILDS = {"user-service", "product-service", "order-service", "detection-service", "context-service",
          "monitoring-worker", "context-integration", "workflow-dispatcher", "mock-analysis", "incident-management",
          "stage97-pg-tests"}
VOLUMES = {
    "user-db": {"users"}, "product-db": {"products"}, "order-db": {"orders"},
    "user-service": {"user-logs"}, "product-service": {"product-logs"}, "order-service": {"order-logs"},
    "logging-files": {"user-logs", "product-logs", "order-logs", "beat-registry"},
    "filebeat": {"user-logs", "product-logs", "order-logs", "beat-registry"}, "elasticsearch": {"elastic-data"},
    "monitoring-worker": {"monitoring-data"}, "context-integration": {"monitoring-data"},
    "workflow-dispatcher": {"monitoring-data"}, "mock-analysis": {"monitoring-data"},
    "workflow-n8n": {"stage95-n8n-data"}, "incident-management": {"monitoring-data", "incident-data"},
}
BINDS = {"filebeat": {"logging/filebeat.yml"}, "logging-setup": {"logging/bootstrap.py"},
         "workflow-n8n": {"workflows/detection-incident.json"}}
NETWORKS = {"default", "logging", "workflow-stage95", "incident-management"}
READER_KEYS = {"DETECTION_ES_API_KEY", "CONTEXT_ES_API_KEY", "MONITORING_ES_API_KEY"}
PHASE_ACTIONS = {
    "9.7B": {"build", "infra", "keys", "services", "schema", "workers", "readiness", "workflow-probe",
             "normal", "postgres", "stop"},
    "9.7C": {"readiness", "fault", "stop"},
}


class GateError(Exception):
    pass


def check(condition, code):
    if not condition:
        raise GateError(code)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan_hash():
    path = PLAN_DIR / "test_plan.json"
    expected = (PLAN_DIR / "test_plan.sha256").read_text(encoding="ascii").strip()
    check(digest(path) == expected, "TEST_PLAN_HASH_MISMATCH")
    plan = json.loads(path.read_text(encoding="utf-8"))
    for name, value in plan["sha256_inputs"].items():
        item = (ROOT / name).resolve()
        check(item.is_relative_to(ROOT) and digest(item) == value, "FROZEN_PLAN_INPUT_CHANGED")
    return expected


def external(path):
    value = Path(path).resolve()
    check(not value.is_relative_to(ROOT.parent), "USE_EXTERNAL_STAGE97_STATE_DIRECTORY")
    return value


def read_env(path, *, live=False, allow_pending=False):
    allowed = set(read_env_names())
    values = {}
    for line in path.read_text(encoding="ascii").splitlines():
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        check(sep and name in allowed and name not in values and re.fullmatch(r"[A-Za-z0-9_=-]+", value),
              "INVALID_ENV_LINE")
        values[name] = value
    check(values.keys() == allowed, "ENV_KEYS_MISSING")
    for name in allowed - READER_KEYS:
        if name.endswith("_ENABLED"):
            check(values[name] == "true", "WORKER_MUST_BE_ENABLED_AT_APPROVED_START")
        elif live:
            check(re.fullmatch(r"[A-Za-z0-9_-]{32,128}", values[name]) and not values[name].startswith("TEMPLATE_"),
                  "SET_FRESH_ISOLATED_CREDENTIALS")
    if live:
        secrets = [value for name, value in values.items() if not name.endswith("_ENABLED") and value != "STAGE97_PENDING"]
        check(len(secrets) == len(set(secrets)), "ISOLATED_CREDENTIALS_MUST_BE_DISTINCT")
        for name in READER_KEYS:
            check((allow_pending and values[name] == "STAGE97_PENDING")
                  or (values[name] != "STAGE97_PENDING" and len(values[name]) >= 24), "ES_READER_KEYS_REQUIRED")
    return values


def read_env_names():
    return [line.partition("=")[0] for line in (PLAN_DIR / "stage97.env.example").read_text().splitlines()
            if "=" in line and not line.startswith("#")]


def approval(path, action, now=None):
    decision = json.loads(external(path).read_text(encoding="utf-8"))
    current = now or datetime.now(timezone.utc)
    expiry = datetime.fromisoformat(decision["expires_at"])
    phase = decision.get("phase")
    actions = set(decision.get("actions", []))
    check(decision.get("approved") is True and decision.get("project") == PROJECT
          and Path(decision["worktree"]).resolve() == ROOT and decision["test_plan_sha256"] == plan_hash()
          and re.fullmatch(r"[A-Za-z0-9_-]{4,80}", decision.get("approval_id", ""))
          and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", decision.get("operator", ""))
          and expiry.tzinfo is not None and current < expiry
          and actions <= PHASE_ACTIONS.get(phase, set()) and action in actions
          and (action not in {"normal", "fault"} or decision.get("max_order_requests") == 1),
          "NO_MATCHING_OPERATOR_APPROVAL")
    return decision


def env_base():
    keep = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "USERPROFILE", "APPDATA",
            "LOCALAPPDATA", "TEMP", "TMP", "PROGRAMFILES", "PROGRAMFILES(X86)", "COMSPEC",
            "HOMEDRIVE", "HOMEPATH", "USERNAME", "NUMBER_OF_PROCESSORS", "OS"}
    return {key: value for key, value in os.environ.items() if key.upper() in keep}


def command(args, *, timeout=20, values=None):
    return subprocess.run(args, cwd=ROOT, env={**env_base(), **(values or {})}, timeout=timeout,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout


def compose(args, *, values, timeout=20):
    prefix = ["docker", "compose", "--project-directory", str(ROOT), "--env-file",
              str(PLAN_DIR / "stage97.env.example"), "-p", PROJECT]
    for profile in PROFILES:
        prefix.extend(("--profile", profile))
    for file in COMPOSE:
        prefix.extend(("-f", file))
    return command([*prefix, *args], timeout=timeout, values=values)


def audit_config(config, *, fault=None):
    check(config.get("name") == PROJECT and set(config["services"]) == SERVICES, "UNEXPECTED_PROJECT_OR_SERVICE_SET")
    for kind in ("networks", "volumes"):
        resources = config[kind]
        expected = NETWORKS if kind == "networks" else set().union(*VOLUMES.values())
        check(set(resources) == expected, "UNEXPECTED_RESOURCE_SET")
        for key, spec in resources.items():
            check(not spec.get("external") and spec["name"] == f"{PROJECT}_{key}"
                  and not spec.get("driver_opts"), "SHARED_RESOURCE")
            if kind == "networks":
                check(spec.get("internal") is True, "NETWORK_NOT_INTERNAL")

    for name, service in config["services"].items():
        env = service.get("environment", {})
        check(not any(service.get(key) for key in ("container_name", "privileged", "env_file", "extra_hosts",
                                                 "devices", "links", "external_links", "secrets", "configs"))
              and service.get("network_mode") in {None, "none"}
              and not any(re.search(r"OPENAI|GEMINI|LLM_", key) for key in env), "ISOLATION_VIOLATION")
        if name != "logging-files":
            expected_network = ("workflow-stage95" if name in {"workflow-n8n", "workflow-dispatcher", "mock-analysis"}
                                else "incident-management" if name == "incident-management"
                                else "default" if name in {"user-db", "product-db", "order-db",
                                                           "user-service", "product-service", "order-service",
                                                           "stage97-pg-tests"}
                                else "logging")
            check(set(service.get("networks", {})) == {expected_network}, "UNEXPECTED_NETWORK_ATTACHMENT")
        ports = [(port["host_ip"], int(port["published"]), int(port["target"]), port.get("protocol", "tcp"))
                 for port in service.get("ports", [])]
        target = 9200 if name == "elasticsearch" else 5678 if name == "workflow-n8n" else 8000
        check(ports == ([("127.0.0.1", PORTS[name], target, "tcp")] if name in PORTS else []), "UNEXPECTED_PORT")
        volumes, binds = set(), set()
        for mount in service.get("volumes", []):
            if mount["type"] == "volume":
                volumes.add(mount["source"])
                if name == "filebeat" and mount["source"] != "beat-registry":
                    check(mount.get("read_only") is True, "FILEBEAT_LOG_MOUNT_WRITABLE")
            else:
                path = Path(mount["source"]).resolve()
                check(mount["type"] == "bind" and mount.get("read_only") is True and path.is_relative_to(ROOT),
                      "UNAPPROVED_BIND")
                binds.add(path.relative_to(ROOT).as_posix())
        check(volumes == VOLUMES.get(name, set()) and binds == BINDS.get(name, set()), "UNAPPROVED_MOUNT")
        if name in BUILDS:
            build = service["build"]
            check(Path(build["context"]).resolve() == ROOT and not build.get("additional_contexts"), "WRONG_BUILD_CONTEXT")
        if name in {"order-service", "product-service"}:
            expected_fault = fault[1] if fault and fault[0] == name else ""
            check(env.get("LAB_FAULT", "") == expected_fault and env.get("LAB_ENABLED", "0") ==
                  ("1" if expected_fault else "0"), "UNEXPECTED_FAULT")
    settings = {name: service.get("environment", {}) for name, service in config["services"].items()}
    for name in ("workflow-dispatcher", "mock-analysis"):
        check(settings[name].get("WORKFLOW_ANALYSIS_PROVIDER") == "mock"
              and settings[name].get("WORKFLOW_EXTERNAL_ALLOWED") == "false", "NON_MOCK_PROVIDER")
    check(settings["workflow-dispatcher"].get("WORKFLOW_N8N_URL") == "http://workflow-n8n:5678"
          and settings["monitoring-worker"].get("MONITORING_DETECTION_URL") == "http://detection-service:8000"
          and settings["monitoring-worker"].get("MONITORING_START_POLICY") == "START_FROM_NOW"
          and settings["monitoring-worker"].get("MONITORING_LOOKBACK_SECONDS") == "0"
          and settings["context-integration"].get("CONTEXT_INTEGRATION_URL") == "http://context-service:8000"
          and settings["incident-management"].get("INCIDENT_SOURCE_STORAGE_PATH") == "/source/monitoring.sqlite"
          and re.fullmatch(r"postgresql://user_app:[A-Za-z0-9_-]+@user-db:5432/users",
                           settings["stage97-pg-tests"].get("TEST_PG_ADMIN_URL", "")),
          "WRONG_INTERNAL_CONTRACT")
    workflow = json.loads((ROOT / "workflows/detection-incident.json").read_text())
    check([node["parameters"]["url"] for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.httpRequest"]
          == ["http://mock-analysis:8000/analyze/package"], "EXTERNAL_WORKFLOW_TARGET")


def local_daemon():
    name = command(["docker", "context", "show"]).strip()
    endpoint = command(["docker", "context", "inspect", name, "--format", "{{.Endpoints.docker.Host}}"]).strip()
    check(endpoint.startswith("npipe:////./pipe/"), "NOT_LOCAL_DOCKER_DESKTOP")


def resources():
    local_daemon()
    info = json.loads(command(["docker", "info", "--format", "{{json .}}"]))
    host = json.loads(command(["powershell.exe", "-NoProfile", "-Command",
                               "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize,"
                               "FreePhysicalMemory | ConvertTo-Json -Compress"]))
    listeners = command(["netstat.exe", "-ano", "-p", "tcp"])
    busy = sorted(port for port in PORTS.values() if re.search(rf":{port}\s+\S+\s+LISTENING", listeners))
    running = command(["docker", "ps", "--format", "{{.Names}} {{.Ports}}"]).splitlines()
    usage = command(["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.CPUPerc}} {{.MemUsage}}"],
                    timeout=30).splitlines()
    objects = {}
    for key, args in {"containers": ["ps", "-a"], "networks": ["network", "ls"],
                      "volumes": ["volume", "ls"]}.items():
        objects[key] = command(["docker", *args, "--filter", f"label=com.docker.compose.project={PROJECT}",
                                "--format", "{{.ID}}" if key == "containers" else "{{.Name}}"]).splitlines()
    return {"docker_version": info["ServerVersion"], "compose_version": command(["docker", "compose", "version"]).strip(),
            "host_cpu": os.cpu_count(), "docker_cpu": info["NCPU"], "docker_memory_bytes": info["MemTotal"],
            "host_free_memory_bytes": host["FreePhysicalMemory"] * 1024,
            "host_total_memory_bytes": host["TotalVisibleMemorySize"] * 1024,
            "disk_free_bytes": shutil.disk_usage(ROOT).free, "busy_stage97_ports": busy, "stage97_objects": objects,
            "running": running, "running_usage": usage,
            "images": command(["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}} {{.Size}}"]).splitlines()}


def static(values, *, fault=None):
    config = json.loads(compose(["config", "--format", "json"], values=values))
    audit_config(config, fault=fault)
    return {"project": PROJECT, "services": sorted(config["services"]), "ports": PORTS,
            "networks": sorted(config["networks"]), "volumes": sorted(config["volumes"])}
