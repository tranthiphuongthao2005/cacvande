$ErrorActionPreference = 'Stop'

function Get-LfSha256([string] $path) {
  $resolved = (Resolve-Path -LiteralPath $path).Path
  $data = [IO.File]::ReadAllText($resolved, [Text.Encoding]::UTF8).Replace("`r`n", "`n")
  $hash = [Security.Cryptography.SHA256]::Create()
  try {
    $bytes = $hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($data))
    return [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
  } finally { $hash.Dispose() }
}

$dir = 'experiments/gemini_smoke_7b1'
$id = 'gemini-smoke-7b1-005'
$model = 'gemini-3.1-flash-lite'
$trace = 'fbb725cc95d116024e29a4935b86d3c4'
$keyFile = Join-Path (Get-Location) '.env.gemini.local'
if ([string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)) {
  if (-not (Test-Path -LiteralPath $keyFile)) { throw 'Local Gemini key file missing' }
  $keyLine = [IO.File]::ReadAllText($keyFile, [Text.Encoding]::UTF8).Trim()
  if ($keyLine -notmatch '^GEMINI_API_KEY=\S+$') { throw 'Local Gemini key file is invalid' }
  $env:GEMINI_API_KEY = $keyLine.Substring('GEMINI_API_KEY='.Length)
  Remove-Variable keyLine
}
$a = Get-Content -Raw -Encoding UTF8 "$dir/gemini-smoke-7b1-005.json" | ConvertFrom-Json
$project = $a.project
if ([string]::IsNullOrWhiteSpace($project)) { throw 'Approved project missing' }
foreach ($prior in '001','002','003','004') {
  $old = Get-Content -Raw -Encoding UTF8 -LiteralPath "$dir/gemini-smoke-7b1-$prior.json" | ConvertFrom-Json
  if ($old.approval_reuse_allowed -ne $false) {
    throw "Validation failed [${prior}.approval_reuse_allowed]: expected False"
  }
}
$expectedImage = $a.image_id
if ($expectedImage -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Approved image ID missing' }
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
  fresh_quota_validity_minutes = 30
  image_id = $expectedImage
  image_reference = 'thesis-log-anomaly-llm-service:latest'
  google_genai_version = '1.68.0'
  prompt_version = 'rca-evidence-v1'
  prompt_sha256 = '1b28c9aa3273ec1e5157a5b8c31cd6dcc82320ede6b2791a28bdab4dd0a6f2a8'
  canonical_schema_sha256 = '725c6357f787126c18015e52b3df351259b60de2aa49e973b7769487a7365989'
  incident_schema_sha256 = '1e82caed7da1e7fd1328bc427fb4fe86c7eaa50db966c50d120fd663335edb4a'
}
foreach ($field in $expectedScope.Keys) {
  if ($a.$field -ne $expectedScope[$field]) {
    throw "Validation failed [${field}]: expected '$($expectedScope[$field])', actual '$($a.$field)'"
  }
}
$expectedGeneration = [ordered]@{
  response_mime_type = 'application/json'
  schema_field = 'response_json_schema'
  max_output_tokens = 1200
  candidate_count = 1
  thinking_level = 'MINIMAL'
  automatic_function_calling = $false
  validation_retries = 0
  sdk_attempts = 1
  timeout_ms = 20000
  api_version = 'v1beta'
}
foreach ($field in $expectedGeneration.Keys) {
  if ($a.generation_configuration.$field -ne $expectedGeneration[$field]) {
    throw "Validation failed [generation_configuration.${field}]"
  }
}
if ($null -eq $a.execution_ledger -or $a.execution_ledger.gemini_calls -ne 0 -or
    $a.execution_ledger.openai_calls -ne 0 -or $a.execution_ledger.evaluation_calls -ne 0 -or
    $a.execution_ledger.cost_usd -ne 0 -or
    $a.execution_ledger.generation_attempts.Count -ne 0 -or
    (Test-Path -LiteralPath "$dir/$id.activation.json") -or
    (Test-Path -LiteralPath "$dir/$id.execution.json") -or
    (Test-Path -LiteralPath "$dir/$id.results.json")) {
  throw 'Activation or execution already recorded'
}

$q = $a.quota_evidence
if ($null -ne $q -and $q.project -ne $project) {
  throw "Quota scope mismatch [quota_evidence.project]: expected '$project', actual '$($q.project)'"
}
if ($a.quota_status -ne 'OPERATOR_ATTESTED' -or $null -eq $q -or
    $q.model -ne $model -or $q.billing_tier -ne 'Free Tier' -or
    [string]::IsNullOrWhiteSpace($q.operator_observed_at_utc)) {
  throw 'Validation failed [quota_status or quota_evidence model, billing_tier, operator_observed_at_utc]'
}
$observed = [DateTimeOffset]::Parse($q.operator_observed_at_utc)
foreach ($metric in 'rpm','tpm','rpd') {
  $m = $q.$metric
  if ($null -eq $m -or $null -eq $m.limit -or $m.limit -le 0 -or
      ($null -ne $m.used -and ($m.used -lt 0 -or $m.limit -le $m.used))) {
    throw "Invalid or exhausted quota: $metric"
  }
}
$budget = $a.quota_budget_check
if ($null -eq $budget -or $budget.fits_reported_limits -ne $true -or
    $budget.remaining_quota_verified -ne $false -or
    $budget.estimated_units_total -le 0 -or
    $q.rpm.limit -lt 2 -or $q.rpd.limit -lt 2 -or
    $q.tpm.limit -lt $budget.estimated_units_total) {
  throw 'Insufficient quota for the approved pair'
}

$freeze = 'experiments/benchmark_7a8r_exploratory'
$index = "$freeze/freeze_manifest.sha256"
if ((Get-LfSha256 $index) -ne $a.freeze_index_sha256) {
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
$imageId = docker image inspect --format '{{.Id}}' $a.image_reference
if ($LASTEXITCODE -ne 0 -or $imageId -ne $expectedImage) { throw 'Validation failed [image_id]' }
$autoscale = docker ps -q --filter 'name=^/autoscale-demo-control-plane$'
if ($LASTEXITCODE -ne 0 -or $autoscale) {
  throw 'Autoscale demo is running or its status is unavailable'
}

$compose = @('--env-file','.env.elk','--env-file','.env.context','--env-file','.env.detection',
  '-f','compose.yaml','-f','compose.logging.yaml','-f','compose.context.yaml',
  '-f','compose.detection.yaml','-f','compose.llm.yaml')
$started = [DateTimeOffset]::UtcNow
if ($observed -gt $started -or ($started - $observed).TotalMinutes -gt 30) {
  throw 'Validation failed [quota_evidence.operator_observed_at_utc]: future or older than 30 minutes'
}
$expires = $started.AddMinutes(30)
$activation = @{approval_id=$a.approval_id; trace_id=$a.trace_id; model=$a.model;
  activated_at_utc=$started.ToString('o'); expires_at_utc=$expires.ToString('o'); minimum_interval_seconds=10
  image_id=$expectedImage
  prompt_sha256=$a.prompt_sha256
  canonical_schema_sha256=$a.canonical_schema_sha256
  freeze_index_sha256=$a.freeze_index_sha256
  quota_observed_at_utc=$observed.ToUniversalTime().ToString('o')}
$file = [IO.File]::Open((Join-Path (Get-Location) "$dir/gemini-smoke-7b1-005.activation.json"), [IO.FileMode]::CreateNew)
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
$override = Join-Path ([IO.Path]::GetTempPath()) ("gemini-7b1-005-" + [guid]::NewGuid().ToString('N') + ".yaml")
try {
  [IO.File]::WriteAllLines($override, @('services:', '  llm-service:', "    image: '$($a.image_reference)'"))
  docker compose @compose -f $override up -d --no-build --pull never --no-deps --force-recreate llm-service
  if ($LASTEXITCODE -ne 0) { throw 'LLM activation failed' }
  $containerId = docker compose @compose ps -q llm-service
  if ($LASTEXITCODE -ne 0 -or -not $containerId) { throw 'Validation failed [runtime.container_id]' }
  $runtimeImage = docker inspect --format '{{.Image}}' $containerId
  if ($LASTEXITCODE -ne 0 -or $runtimeImage -ne $expectedImage) { throw 'Validation failed [runtime.image_id]' }
  $ready = $null
  for ($i=0; $i -lt 10 -and $null -eq $ready; $i++) {
    try { $ready = Invoke-RestMethod http://127.0.0.1:8016/ready -TimeoutSec 3 }
    catch { Start-Sleep -Seconds 2 }
  }
  if ([DateTimeOffset]::UtcNow -ge $expires) { throw 'Validation failed [expires_at_utc]' }
  $expectedReady = @{provider='gemini'; model=$model; validation_retries=0; call_cap=2;
    calls_remaining=2; prompt_version=$a.prompt_version; input_budget=7000; max_output_tokens=1200}
  foreach ($field in $expectedReady.Keys) {
    if ($null -eq $ready -or $ready.$field -ne $expectedReady[$field]) { throw "Validation failed [ready.${field}]" }
  }
  $ready | Select-Object provider,model,validation_retries,call_cap,calls_remaining
  $activation | ConvertTo-Json
} catch {
  $env:LLM_ALLOW_EXTERNAL = '0'
  $env:LLM_CALL_CAP = '0'
  docker compose @compose stop llm-service
  if ($LASTEXITCODE -ne 0) { Write-Warning 'Unable to confirm the external gate is closed' }
  throw
} finally {
  if (Test-Path -LiteralPath $override) { Remove-Item -LiteralPath $override }
}
