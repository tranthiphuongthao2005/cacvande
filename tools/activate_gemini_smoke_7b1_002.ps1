$ErrorActionPreference = 'Stop'
$dir = 'experiments/gemini_smoke_7b1'
$id = 'gemini-smoke-7b1-002'
$model = 'gemini-3.1-flash-lite'
$trace = '8cc314768cf9c12e300243a20669ad28'
$project = 'Dự án Gemini 2'
$a = Get-Content -Raw -Encoding UTF8 "$dir/gemini-smoke-7b1-002.json" | ConvertFrom-Json
$old = Get-Content -Raw -Encoding UTF8 -LiteralPath "$dir/gemini-smoke-7b1-001.json" | ConvertFrom-Json
if ($old.approval_reuse_allowed -ne $false) {
  throw "Approval scope mismatch [001.approval_reuse_allowed]: expected False, actual '$($old.approval_reuse_allowed)'"
}
$expectedScope = [ordered]@{
  approval_id = $id
  approval_status = 'APPROVED'
  operator_id = 'local-project-operator'
  decision_source = 'USER_OPERATOR_DECLARATION'
  provider = 'gemini'
  project = $project
  billing_tier = 'Free Tier'
  model = $model
  trace_id = $trace
  maximum_generation_calls = 2
  single_service_calls = 1
  cross_service_calls = 1
  retry = 0
  maximum_cost_usd = 0
  runtime_approval_validity_minutes = 30
  minimum_interval_seconds = 10
  evaluation_calls = 0
  openai_calls = 0
}
foreach ($field in $expectedScope.Keys) {
  if ($a.$field -ne $expectedScope[$field]) {
    throw "Approval scope mismatch [${field}]: expected '$($expectedScope[$field])', actual '$($a.$field)'"
  }
}
if ($null -eq $a.execution_ledger -or $a.execution_ledger.gemini_calls -ne 0 -or
    $a.execution_ledger.generation_attempts.Count -ne 0 -or
    @(Get-ChildItem -LiteralPath $dir -Filter "$id.*.json").Count -ne 0) {
  throw 'Activation or execution already recorded'
}

$q = $a.quota_evidence
if ($null -ne $q -and $q.project -ne $project) {
  throw "Quota scope mismatch [quota_evidence.project]: expected '$project', actual '$($q.project)'"
}
if ($a.quota_status -ne 'OPERATOR_ATTESTED' -or $null -eq $q -or
    $q.model -ne $model -or $q.billing_tier -ne 'Free Tier' -or
    [string]::IsNullOrWhiteSpace($q.operator_observed_at_utc)) {
  throw 'Fresh quota with an operator observation timestamp is required'
}
$observed = [DateTimeOffset]::Parse($q.operator_observed_at_utc)
foreach ($metric in 'rpm','tpm','rpd') {
  $m = $q.$metric
  if ($null -eq $m.used -or $null -eq $m.limit -or
      $m.used -lt 0 -or $m.limit -le $m.used) { throw "Invalid or exhausted quota: $metric" }
}
$budget = $a.quota_budget_check
if ($null -eq $budget -or $budget.fits_reported_limits -ne $true -or
    $budget.estimated_units_total -le 0 -or
    ($q.rpm.limit - $q.rpm.used) -lt 2 -or ($q.rpd.limit - $q.rpd.used) -lt 2 -or
    ($q.tpm.limit - $q.tpm.used) -lt $budget.estimated_units_total) {
  throw 'Insufficient quota for the approved pair'
}

$freeze = 'experiments/benchmark_7a8r_exploratory'
$index = "$freeze/freeze_manifest.sha256"
if ((Get-FileHash -LiteralPath $index -Algorithm SHA256).Hash -ne $a.freeze_index_sha256) {
  throw 'Freeze index checksum mismatch'
}
$rows = @(Get-Content -LiteralPath $index)
if ($rows.Count -ne 8) { throw 'Unexpected freeze entry count' }
foreach ($row in $rows) {
  $parts = $row -split '  ',2
  if ($parts.Count -ne 2 -or
      (Get-FileHash -LiteralPath (Join-Path $freeze $parts[1]) -Algorithm SHA256).Hash -ne $parts[0]) {
    throw 'Frozen artifact checksum mismatch'
  }
}
$inference = Get-Content -Raw -Encoding UTF8 -LiteralPath "$freeze/inference_manifest.json" | ConvertFrom-Json
if (@($inference.records).Count -ne 10 -or
    @($inference.records | Where-Object {
      (Split-Path -Leaf (Split-Path -Parent $_.snapshots.cross_service.path)) -eq $trace
    }).Count -ne 0) {
  throw 'Unexpected frozen cohort or smoke trace overlap'
}
foreach ($mode in 'single_service','cross_service') {
  $inputSpec = $a.inputs.$mode
  if ($inputSpec.trace_id -ne $trace -or
      (Get-FileHash -LiteralPath $inputSpec.path -Algorithm SHA256).Hash -ne $inputSpec.sha256) {
    throw "Smoke input checksum or trace mismatch: $mode"
  }
}

if ([string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)) {
  throw 'Run in the PowerShell session that already holds the Gemini key'
}
$autoscale = docker inspect --format '{{.State.Status}}' autoscale-demo-control-plane
if ($LASTEXITCODE -ne 0 -or $autoscale -ne 'exited') {
  throw 'Autoscale demo is not confirmed stopped'
}

$compose = @('--env-file','.env.elk','--env-file','.env.context','--env-file','.env.detection',
  '-f','compose.yaml','-f','compose.logging.yaml','-f','compose.context.yaml',
  '-f','compose.detection.yaml','-f','compose.llm.yaml')
$started = [DateTimeOffset]::UtcNow
if ($observed -gt $started -or ($started - $observed).TotalMinutes -gt 30) {
  throw 'Quota observation is from the future or older than 30 minutes'
}
$expires = $started.AddMinutes(30)
$activation = @{approval_id=$a.approval_id; trace_id=$a.trace_id; model=$a.model;
  activated_at_utc=$started.ToString('o'); expires_at_utc=$expires.ToString('o'); minimum_interval_seconds=10
  freeze_index_sha256=$a.freeze_index_sha256
  quota_observed_at_utc=$observed.ToUniversalTime().ToString('o')}
$file = [IO.File]::Open((Join-Path (Get-Location) "$dir/gemini-smoke-7b1-002.activation.json"), [IO.FileMode]::CreateNew)
try {
  $bytes = [Text.Encoding]::UTF8.GetBytes(($activation | ConvertTo-Json))
  $file.Write($bytes, 0, $bytes.Length)
} finally { $file.Dispose() }
$env:LLM_PROVIDER = 'gemini'
$env:LLM_MODEL = $a.model
$env:LLM_ALLOW_EXTERNAL = '1'
$env:LLM_CALL_CAP = '2'
$env:LLM_VALIDATION_RETRIES = '0'
$env:LLM_GEMINI_FREE_TIER_CONFIRMED = '1'
$env:LLM_GEMINI_SMOKE_APPROVAL_ID = $a.approval_id
$env:LLM_GEMINI_SMOKE_TRACE_ID = $a.trace_id
$env:LLM_GEMINI_SMOKE_EXPIRES_UTC = $expires.ToString('o')
try {
  docker compose @compose up -d --no-build --no-deps --force-recreate llm-service
  if ($LASTEXITCODE -ne 0) { throw 'LLM activation failed' }
  $ready = $null
  for ($i=0; $i -lt 10 -and $null -eq $ready; $i++) {
    try { $ready = Invoke-RestMethod http://127.0.0.1:8016/ready -TimeoutSec 3 }
    catch { Start-Sleep -Seconds 2 }
  }
  if ([DateTimeOffset]::UtcNow -ge $expires -or $ready.provider -ne 'gemini' -or $ready.model -ne $a.model -or
      $ready.validation_retries -ne 0 -or $ready.call_cap -ne 2 -or $ready.calls_remaining -ne 2) { throw 'Unexpected readiness' }
  $ready | Select-Object provider,model,validation_retries,call_cap,calls_remaining
  $activation | ConvertTo-Json
} catch {
  $env:LLM_ALLOW_EXTERNAL = '0'
  $env:LLM_CALL_CAP = '0'
  docker compose @compose stop llm-service
  if ($LASTEXITCODE -ne 0) { Write-Warning 'Unable to confirm the external gate is closed' }
  throw
}
