# Gemini smoke 006: observation mismatch

Smoke 006 used one Gemini generation call for Single-Service Order. The API returned HTTP 502
`INVALID_MODEL_OUTPUT`; the sanitized application log recorded
`llm_validation_failure reason=OBSERVATION_MISMATCH`. Cross-Service was not called, and the LLM
container was stopped. The closed ledger is
`experiments/gemini_smoke_7b1/gemini-smoke-7b1-006.execution.json`.

The response body was not retained, so the exact observation and its generated value cannot be
reconstructed. The known failure is at `validate_model`: an observation's `value` differed from the
indexed event field for its `event_id` and `kind`. It was not an upstream 503 or a schema parse
failure. The original prompt did not state the exact representation required for each kind. In
addition, the validator rejected a `dependency_failure` observation for `dependency_exhausted`
even when that event named a dependency. The smoke Context contains such an event.

The revised `rca-evidence-v2` prompt requires exact copying of `event_id`, `service_name`, and
`value`, including decimal status strings without an HTTP prefix. It allows the model to omit a
fact it cannot copy exactly. The validator now accepts `dependency_failure` for both
`dependency_attempt_failed` and `dependency_exhausted` when the dependency name matches the same
event. Incorrect values remain rejected. Sanitized diagnostics include the observation kind,
without logging generated values, event content, credentials, or raw provider output.

For the next smoke run, `ObservationMismatch` records whether the mismatch is in
`observations[i]` or `evidence[i].observation`, the cited event ID, kind, expected value from the
prepared Context, and generated value only when it matches a small allowlist of service names,
event messages, or HTTP status forms. Other generated values are withheld, with length recorded.
The Single-Service and Cross-Service smoke runners copy only these vetted fields from the
container log into their result JSON on failure. Provider failures instead retain allowlisted
category, stage, upstream status, provider error code, receipt, and retryability. The full model
response is not included in logs or result JSON.

Smoke 007 also has an explicit, one-response raw capture mode. If canonical JSON validation or
evidence validation fails, the service writes the exact Gemini response text once to a 64 KiB
maximum file in container tmpfs, restricted to the approved trace and approval ID. The operator
runner reads it before stopping the container and saves the bytes under
`experiments/gemini_smoke_7b1/private/`, which `.gitignore` excludes; `.dockerignore` already
excludes all experiments from build context. The result JSON keeps only path, byte count, SHA-256,
and capture status. This local file is plaintext and should be reviewed or deleted after diagnosis.
Upstream errors with no model response have no raw text to save.

Offline verification: 45 LLM/Gemini/diagnostic/capture tests passed, including a valid
`dependency_exhausted` observation, rejected mismatches, nested evidence location, and filtering
of unapproved log fields. A network-disabled Docker probe verified that the operator can copy
exact bytes from tmpfs to the ignored local directory, then removed the probe file. The current
local image ID is recorded in the smoke 007 draft.
The LLM container remains stopped. Live success of v2 has not yet been measured.

The frozen exploratory evaluation plan references `rca-evidence-v1`. Preserve that record.
Any v2 smoke or 20-call evaluation needs a new approval, image/prompt hash, and explicit protocol
version; it must not be recorded as a run of the frozen v1 configuration.
