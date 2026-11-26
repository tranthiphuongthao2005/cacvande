# Stage 9.7 — Isolated runtime setup

The CLI fixes the Compose project, worktree and file list. 9.7A uses only preflight. Live actions need a separate unexpired approval, frozen digest, scoped action list and fresh external env file. Secrets, ledger and evidence stay outside the checkout.

| Service | Internal | Host loopback |
| --- | --- | --- |
| User/Product/Order | 8000; DB 5432 only internal | 19011/19012/19013 |
| Detection and Context | 8000 on logging | 19014/19015 |
| Incident Management | 8000 | 19017 |
| Elasticsearch | 9200 | 19297 |
| New n8n | 5678, pinned 2.48.7 | 15678 |
| Mock Analysis/workers | Mock 8000, internal only | None |

The selected profiles exclude Kibana, shared scenario n8n/Adapter and LLM. Four networks are internal and project-scoped. PostgreSQL data, Elasticsearch, Filebeat registry and three producer log volumes are project-scoped. Filebeat reads exactly the producer volumes, read-only, with no Docker socket/autodiscover. Three read-only file binds come from this worktree. Monitoring/Context/Workflow/Mock share monitoring-data at /data/monitoring.sqlite. Incident uses that database at /source/monitoring.sqlite and incident-data for its own /data/incidents.sqlite. n8n has an independent volume. The PostgreSQL runner uses a single isolated user-db admin account inside the default network and the test suite creates and cleans only generated database names. No host DB port. Docker build may need Python package network access with separate approval. Mock runtime has no provider secrets or model downloads.

## Read-only PowerShell

~~~powershell
$python = "..\thesis-log-anomaly\.venv\Scripts\python.exe"
$target = @('--worktree', (Get-Location).Path, '--project', 'thesis-e2e-stage97')
& $python -B -m tools.stage97_runtime preflight @target
& $python -B -m tools.stage97_runtime preflight @target --resources
~~~

This path works when Windows execution policy blocks the optional PowerShell wrapper. No execution policy change is required.

## After separate 9.7B approval only

Copy the env template to an ACL-protected location outside the checkout. Replace placeholders with fresh distinct credentials, keeping STAGE97_PENDING for the three ES reader keys before provisioning. Use the approval template outside the checkout, fill exact scope and digest. Do not echo env or merged JSON. Run each line separately, stop on a nonzero exit code.

~~~powershell
$live = $target + @('--env-file', $isolatedEnv, '--approval', $approvedDecision, '--artifact-dir', $isolatedEvidence)
& $python -B -m tools.stage97_runtime build @live
& $python -B -m tools.stage97_runtime infra @live
# Wait for owned ES and PostgreSQL to become healthy.
& $python -B -m tools.stage97_runtime keys @live
& $python -B -m tools.stage97_runtime services @live
& $python -B -m tools.stage97_runtime schema @live
# Import and publish in the isolated n8n UI, then authorize the declared production probe.
& $python -B -m tools.stage97_runtime workers @live
& $python -B -m tools.stage97_runtime readiness @live
& $python -B -m tools.stage97_runtime workflow-probe @live
& $python -B -m tools.stage97_runtime normal @live
# Separately authorized PostgreSQL integration suite.
& $python -B -m tools.stage97_runtime postgres @live
~~~

Infra creates three PostgreSQL instances and Elasticsearch. Services runs bootstrap, producers, Filebeat, Detection, Context, Mock Analysis and n8n. Schema verifies dependencies, waits for the index, then seeds the Monitoring floor and initializes Context, Workflow and Incident schemas before workers start. Pre-floor traffic is excluded. Capture unexpected setup anomalies and stop if post-floor probes produce incidents outside the plan.

In the isolated n8n editor at 15678 import workflows/detection-incident.json via **Import from File**, confirm the fixed Mock Analysis node and publish. Record real version, workflow identity and published status. Authorize the synthetic probe explicitly and mark workflow_published_verified only after publication. The probe passes through the production webhook and records the real execution ID from the adapter, response status evidence and binding hashes. It does not insert a business detection event or incident. Observe node-level outcomes in the runtime under the approved scope and retain sanitized metadata only. Raw execution persistence stays disabled. Report any node-level evidence unavailable instead of substituting the HTTP stub. [n8n workflow import](https://docs.n8n.io/build/manage-workflows/export-and-import.md)

For a separately approved 9.7C, pass fault --case E2E-02 through E2E-05 and use collect --trace ACTUAL_TRACE_ID after rollback. The stop action stops only owned Compose services and preserves volumes. Stage 9.7A executes none of these actions.
