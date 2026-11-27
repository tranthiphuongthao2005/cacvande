# Gemini smoke 007 result

Smoke 007 used one Free Tier Gemini 3.1 Flash Lite generation call with `rca-evidence-v2` on
Single-Service Order. The API returned HTTP 502 `INVALID_MODEL_OUTPUT`; Cross-Service was not
attempted. The LLM container was verified stopped. The closed execution ledger is
`experiments/gemini_smoke_7b1/gemini-smoke-7b1-007.execution.json`.

The scoped raw capture succeeded: 2,715 bytes, SHA-256
`4b759176b93bc42253fbf08c908bfaa998571cbceffde5a25896070b9ae3d284`.
Its local plaintext file is under the Git-ignored
`experiments/gemini_smoke_7b1/private/` directory. Neither this document nor the execution
ledger contains the raw model text.

Offline inspection of the captured response found a schema-valid `ModelAnalysis`, three
grounded observations, and two grounded nested evidence observations. The sanitized service log
identified `SUSPECTED_SERVICE_UNGROUNDED`: the model returned `ANALYZED` and assigned
`suspected_root_cause_service=product`, but its two cited events both belong to `order`. Only
`order` events were available in Single-Service Context. The validator correctly rejected the
unsupported root-service assignment. The result JSON's diagnostic field was null because its
operator parser initially only extracted observation mismatches; that parser now accepts all
allowlisted validation reasons. The separate
`experiments/gemini_smoke_7b1/gemini-smoke-7b1-007.diagnostic-recovery.json` records the
safe post-run findings and verified raw-file hash.

`rca-evidence-v3` now instructs the model to assign a suspected root service only when a cited
event belongs to that service. Otherwise it must abstain from root-cause attribution, while it
may retain a qualified hypothesis based on caller evidence. The validator remains strict.
Forty-seven related offline tests passed. Live behavior of v3 has not been measured; smoke 008
has a separate pending draft, image, and prompt hash. The frozen v1 evaluation plan is unchanged.
