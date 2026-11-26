# Stage 9.7 — E2E test plan

Campaign thesis-e2e-stage97-v1 uses a separate Docker stack and Mock Analysis. 9.7A is preparation. 9.7B requires approval for build, startup, n8n production probe and normal smoke. 9.7C requires separate case-specific approval. The plan digest pins runtime code, overlays, case expectations, fault policy and approval inputs. Preserve the frozen version and obtain approval for an amendment before changing expected results.

| Cases | Scope |
| --- | --- |
| E2E-01 | One Order POST, HTTP 201, matching producer/Docker/ES IDs and payload, stable AUTO Rule-based NO_ANOMALY_DETECTED, no trace-specific incident or webhook. |
| E2E-02 | Order processing after dependency lookup, HTTP 500, R01/R04. |
| E2E-03 | Product delay, HTTP 504, R01/R02/R06, inspect late Product completion. |
| E2E-04 | Order request DSN failure, HTTP 503, R01/R03, PostgreSQL stays healthy. |
| E2E-05–07 | Product unavailable, Order 502, R01/R05/R06 and R07 if coherent cross-service evidence exists. 06/07 are evidence aliases for 05. |
| E2E-08/09 | Event replay/conflict and production webhook replay with same bound key. |
| E2E-10/11 | Isolated Context or Mock Analysis outage, preserve incident and truthful pending/failed/unknown status. |
| E2E-12 | Malformed evidence; blocked pending separate fixture and approval. |
| E2E-13/14 | Restart and isolated Elasticsearch outage, verify checkpoints/leases/idempotency. |
| E2E-15 | Incident API read/filter/page, auth, audited lifecycle and 409 on stale record version. |

See the case manifest for evidence, expected business/detection/analysis/incident status, timeouts and cleanup for every case. Only the four supported business faults are automated. Replay, infrastructure and lifecycle cases require separately approved actions and case fixtures.

Processing uses the post-lookup hook. The before-lookup hook adds a stage field that the existing ingest allowlist rejects. Timeout uses inherited Order and Product settings, a 2-second caller deadline, a 2.25-second Product delay and two attempts. Database failure is an Order request DSN failure, not a server crash. Cascade evidence indicates propagation, not verified causation. If R07 evidence is missing, preserve that limitation and mark the applicable expectation partial or failed.

For 9.7C, require normal PASS bound to its evidence hash, approval for the exact case, healthy baseline, inactive fault flags, expiry and an independent rollback observer. Two setup POSTs seed User/Product before activation; each case allows one Order POST with no client repeat. Recreate only the target service. The 90-second window includes restoring normal config, checking inactive flags and confirming /ready. If rollback is unverified, persist ROLLBACK_FAILED and stop. A business status and successful rollback alone do not prove E2E acceptance.

Collect actual trace ID, request status/latency, allowlisted payloads, producer and Docker log IDs, Elasticsearch ID/index, durable detection, context/workflow/incident references and hashes, timeline and API history. Join producer and ES evidence by identity and compare mapped payload fields. For analysis, verify the Context Package hash, stored dispatcher envelope signature, adapter binding, Workflow Result context hash and Incident revision hash. Use durable timestamps to check detection persisted, incident created, analysis started/completed. Preserve an ordering failure if the incident was created too late. Never infer TRACE_COMPLETE from polling or event counts.

The metrics schema defines start/end clocks, units and reporting. Use host monotonic for an elapsed HTTP request. First observed indexed/incident result includes polling delay. Validate Docker VM/host clock consistency before cross-source subtraction. Capture sample count/min/median/mean/max, and p95 only with enough samples. Record Docker/Elasticsearch resource and SQLite storage observations. Mock timing is not real-provider timing. Business trace descriptive confusion counts exclude unscorable traces and report coverage separately. Replay, infrastructure, synthetic workflow probe and duplicate mechanism aliases are excluded from the independent business denominator. No ROC-AUC, LLM RCA accuracy or MeCoLog Microservices accuracy claims.
