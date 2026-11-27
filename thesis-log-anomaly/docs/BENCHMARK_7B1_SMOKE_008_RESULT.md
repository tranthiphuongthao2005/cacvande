# Gemini smoke 008 result

Smoke 008 used one Free Tier Gemini 3.1 Flash Lite generation call with `rca-evidence-v3` for
Single-Service Order. The API returned HTTP 502 `INVALID_MODEL_OUTPUT`; Cross-Service was not
attempted. The LLM container was verified stopped. See the closed
`experiments/gemini_smoke_7b1/gemini-smoke-7b1-008.execution.json`.

The one-response raw capture saved 2,658 bytes locally with SHA-256
`d7d93f7642a6a5c9d92e6ccd89d5ea2a62849e3e9a7297920fec70baed5cf40b` under the
Git-ignored `experiments/gemini_smoke_7b1/private/` directory. The result JSON and
`experiments/gemini_smoke_7b1/gemini-smoke-7b1-008.diagnostic-recovery.json` contain only
sanitized findings, not the raw model text.

The response obeyed the v3 root-service rule: it used `INSUFFICIENT_EVIDENCE` and a null
suspected root service. It listed both `order` and `product` as affected services, while every
direct observation belonged to `order`. The validator correctly reported
`AFFECTED_SERVICE_UNGROUNDED`. The remaining structural claim and evidence checks on this
response passed offline.

A replay checked the raw response SHA-256, the Context snapshot SHA-256, and the prepared
payload SHA-256 recorded for the attempt. The original response reproduced the same validation
error. Removing only `product` from `affected_services` in memory made `validate_model` pass
with `INSUFFICIENT_EVIDENCE` and the existing warnings for incomplete Context and human review.

`rca-evidence-v4` now requires every affected service to have a direct observation with the same
service name. A caller's dependency report alone does not make that dependency a directly
observed affected service. Forty-eight related offline tests passed. The v4 image and smoke 009
draft are prepared separately; live behavior remains unverified. The frozen v1 evaluation plan
remains unchanged.
