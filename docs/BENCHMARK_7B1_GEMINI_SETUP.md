# 7B.1 — Gemini Free Tier

Ứng viên cho smoke là `gemini-3.1-flash-lite` qua Gemini Developer API. Google công bố structured output và giá 0 USD cho đầu vào và đầu ra văn bản ở Free Tier tiêu chuẩn. Project cụ thể cần được kiểm tra riêng. Google cũng nêu dữ liệu Free Tier có thể được dùng để cải thiện sản phẩm. Chỉ dùng một trace smoke ngoài cohort với dữ liệu thử nghiệm đã rà soát. [Model](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite) · [Giá](https://ai.google.dev/gemini-api/docs/pricing) · [Quota](https://ai.google.dev/gemini-api/docs/rate-limits)

## Điều kiện trước smoke

1. Trong Google AI Studio, chọn đúng project chứa key. Kiểm tra mục billing hiển thị **Free**, không có billing trả phí, và mục Rate Limits có quota hoạt động cho đúng model. Kiểm tra RPD còn đủ cho số lượt được duyệt, RPM và TPM phù hợp. Ghi bằng chứng đã che thông tin nhạy cảm và thời điểm kiểm tra. [Billing](https://ai.google.dev/gemini-api/docs/billing) · [Rate Limits của project](https://aistudio.google.com/rate-limit)
2. Operator cấp phê duyệt riêng, ghi ID, model, trace smoke ngoài cohort, số lượt tối đa 2, 0 retry, 0 USD và thời điểm hết hạn UTC. Đối chiếu freeze index bằng checksum để bảo toàn nguồn nghiên cứu tách biệt. Các biến môi trường là bản ghi xác nhận của operator, không tự xác thực billing hay danh tính.
3. Inject key bằng secret manager vào chính tiến trình khởi chạy Compose. Kiểm tra boolean trong container. Thay giá trị mẫu dưới đây bằng dữ liệu đã được duyệt. Dùng một replica và một tiến trình duy nhất. Bộ đếm ở bộ nhớ, vì vậy dừng lượt smoke nếu tiến trình restart và không sử dụng lại phê duyệt đó.

## Recreate an toàn trước phê duyệt

Chạy ngay trong cửa sổ PowerShell đang giữ key mới. Biến môi trường theo tiến trình không tự chuyển sang phiên Codex. Bước này tắt external calls và chỉ thay container LLM.

```powershell
if ([string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)) { throw 'GEMINI_API_KEY is missing in this PowerShell process' }
$env:LLM_PROVIDER = 'gemini'
$env:LLM_MODEL = 'gemini-3.1-flash-lite'
$env:LLM_ALLOW_EXTERNAL = '0'
$env:LLM_CALL_CAP = '0'
$llmCompose = @('--env-file','.env.elk','--env-file','.env.context','--env-file','.env.detection',
  '-f','compose.yaml','-f','compose.logging.yaml','-f','compose.context.yaml',
  '-f','compose.detection.yaml','-f','compose.llm.yaml')
docker compose @llmCompose up -d --no-build --no-deps --force-recreate llm-service
if ($LASTEXITCODE -ne 0) { throw 'LLM container recreate failed' }
docker compose @llmCompose exec -T llm-service python -c "import os; from importlib.metadata import version; print('key_present='+str(bool(os.getenv('GEMINI_API_KEY','').strip()))); print('sdk='+version('google-genai'))"
Invoke-RestMethod http://127.0.0.1:8016/health -TimeoutSec 5
```

Kỳ vọng `key_present=True`, SDK `1.68.0` và `/health` HTTP 200 sau khi khởi động. `/ready` trả HTTP 503 khi external calls tắt. Trước bước sau, điền [hồ sơ phê duyệt](BENCHMARK_7B1_GEMINI_SMOKE_APPROVAL_DRAFT.md).

## Kích hoạt cho smoke đã được duyệt

### Approval 002

Chỉ chạy sau khi operator phê duyệt riêng và hồ sơ 002 ghi `approval_status=APPROVED`, `operator_id=local-project-operator`, `quota_status=OPERATOR_ATTESTED`, model trong quota và số liệu quota mới từ đúng project Free Tier. Chạy từ thư mục dự án trong terminal đang giữ key. Khối này không gửi POST.

```powershell
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)) { throw 'Gemini key missing in this terminal' }
$dir = 'experiments/gemini_smoke_7b1'
$a = Get-Content -Raw -Encoding UTF8 "$dir/gemini-smoke-7b1-002.json" | ConvertFrom-Json
if ($a.approval_id -ne 'gemini-smoke-7b1-002' -or $a.approval_status -ne 'APPROVED' -or
    $a.operator_id -ne 'local-project-operator' -or $a.quota_status -ne 'OPERATOR_ATTESTED' -or
    $a.quota_evidence.model -ne 'gemini-3.1-flash-lite' -or $a.quota_evidence.billing_tier -ne 'Free Tier' -or
    $a.execution_ledger.gemini_calls -ne 0 -or $a.execution_ledger.generation_attempts.Count -ne 0) {
  throw 'Approval or fresh quota evidence missing'
}
if ((Get-FileHash 'experiments/benchmark_7a8r_exploratory/freeze_manifest.sha256').Hash -ne $a.freeze_index_sha256) { throw 'Freeze index mismatch' }
$compose = @('--env-file','.env.elk','--env-file','.env.context','--env-file','.env.detection',
  '-f','compose.yaml','-f','compose.logging.yaml','-f','compose.context.yaml',
  '-f','compose.detection.yaml','-f','compose.llm.yaml')
$started = [DateTimeOffset]::UtcNow
$expires = $started.AddMinutes(30)
$activation = @{approval_id=$a.approval_id; trace_id=$a.trace_id; model=$a.model;
  activated_at_utc=$started.ToString('o'); expires_at_utc=$expires.ToString('o'); minimum_interval_seconds=10}
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
  if ($ready.provider -ne 'gemini' -or $ready.model -ne $a.model -or
      $ready.validation_retries -ne 0 -or $ready.call_cap -ne 2 -or $ready.calls_remaining -ne 2) { throw 'Unexpected readiness' }
  $ready | Select-Object provider,model,validation_retries,call_cap,calls_remaining
  $activation | ConvertTo-Json
} catch {
  $env:LLM_ALLOW_EXTERNAL = '0'
  $env:LLM_CALL_CAP = '0'
  docker compose @compose up -d --no-build --no-deps --force-recreate llm-service
  if ($LASTEXITCODE -ne 0) { Write-Warning 'Cleanup failed. Verify runtime gate is closed.' }
  throw
}
```

### Phê duyệt gemini-smoke-7b1-001

Chạy khối dưới đây từ thư mục `thesis-log-anomaly` trong PowerShell đang giữ key mới của Dự án Gemini 2. Khối này chỉ kích hoạt Gemini và ghi cửa sổ 30 phút, chưa gửi POST. Dùng một lần. Nếu có lỗi hoặc container restart sau khi kích hoạt, giữ ledger và dừng.

```powershell
if ([string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)) { throw 'GEMINI_API_KEY missing in this PowerShell process' }
$llmCompose = @('--env-file','.env.elk','--env-file','.env.context','--env-file','.env.detection',
  '-f','compose.yaml','-f','compose.logging.yaml','-f','compose.context.yaml',
  '-f','compose.detection.yaml','-f','compose.llm.yaml')
$approvalDir = 'experiments/gemini_smoke_7b1'
$approval = Get-Content -Raw -Encoding UTF8 "$approvalDir/gemini-smoke-7b1-001.json" | ConvertFrom-Json
if ($approval.approval_id -ne 'gemini-smoke-7b1-001' -or
    $approval.execution_ledger.gemini_calls -ne 0 -or $approval.execution_ledger.generation_attempts.Count -ne 0) {
  throw 'Unexpected approval or existing generation attempt'
}
if ($approval.quota_status -ne 'OPERATOR_ATTESTED' -or $approval.quota_evidence.model -ne 'gemini-3.1-flash-lite') {
  throw 'Missing operator quota evidence'
}
if ((Get-FileHash 'experiments/benchmark_7a8r_exploratory/freeze_manifest.sha256').Hash -ne $approval.freeze_index_sha256) {
  throw 'Freeze index mismatch'
}
$started = [DateTimeOffset]::UtcNow
$expires = $started.AddMinutes(30)
$env:LLM_PROVIDER = 'gemini'
$env:LLM_MODEL = 'gemini-3.1-flash-lite'
$env:LLM_ALLOW_EXTERNAL = '1'
$env:LLM_CALL_CAP = '2'
$env:LLM_VALIDATION_RETRIES = '0'
$env:LLM_GEMINI_FREE_TIER_CONFIRMED = '1'
$env:LLM_GEMINI_SMOKE_APPROVAL_ID = $approval.approval_id
$env:LLM_GEMINI_SMOKE_TRACE_ID = $approval.trace_id
$env:LLM_GEMINI_SMOKE_EXPIRES_UTC = $expires.ToString('o')
$activation = @{
  approval_id = $approval.approval_id
  trace_id = $approval.trace_id
  activated_at_utc = $started.ToString('o')
  expires_at_utc = $expires.ToString('o')
  model = $env:LLM_MODEL
  minimum_interval_seconds = 10
}
$activationPath = Join-Path (Get-Location) "$approvalDir/gemini-smoke-7b1-001.activation.json"
$file = [IO.File]::Open($activationPath, [IO.FileMode]::CreateNew)
try {
  $bytes = [Text.Encoding]::UTF8.GetBytes(($activation | ConvertTo-Json))
  $file.Write($bytes, 0, $bytes.Length)
} finally { $file.Dispose() }
try {
  docker compose @llmCompose up -d --no-build --no-deps --force-recreate llm-service
  if ($LASTEXITCODE -ne 0) { throw 'LLM activation failed' }
  $ready = $null
  for ($probe = 0; $probe -lt 10 -and $null -eq $ready; $probe++) {
    try { $ready = Invoke-RestMethod http://127.0.0.1:8016/ready -TimeoutSec 3 }
    catch { Start-Sleep -Seconds 2 }
  }
  if ($ready.provider -ne 'gemini' -or $ready.model -ne $env:LLM_MODEL -or
      $ready.validation_retries -ne 0 -or $ready.calls_remaining -ne 2) { throw 'Unexpected readiness' }
  $ready | Select-Object provider,model,validation_retries,call_cap,calls_remaining
  $activation | ConvertTo-Json
} catch {
  $env:LLM_ALLOW_EXTERNAL = '0'
  $env:LLM_CALL_CAP = '0'
  docker compose @llmCompose up -d --no-build --no-deps --force-recreate llm-service
  if ($LASTEXITCODE -ne 0) { Write-Warning 'Cleanup failed. Verify the runtime gate is closed.' }
  throw
}
```

Sau khi nhận readiness, tiếp tục với hai POST có ledger và cleanup trong cửa sổ đã ghi. Không chạy thêm lệnh POST thủ công.

```powershell
$env:LLM_PROVIDER = 'gemini'
$env:LLM_MODEL = 'gemini-3.1-flash-lite'
$env:LLM_ALLOW_EXTERNAL = '1'
$env:LLM_CALL_CAP = '2'
$env:LLM_VALIDATION_RETRIES = '0'
$env:LLM_GEMINI_FREE_TIER_CONFIRMED = '1'
$env:LLM_GEMINI_SMOKE_APPROVAL_ID = '<id-da-duyet>'
$env:LLM_GEMINI_SMOKE_EXPIRES_UTC = '<ISO-8601-UTC-da-duyet>'
$env:LLM_GEMINI_SMOKE_TRACE_ID = '<trace-id-ngoai-cohort-da-duyet>'
$llmCompose = @('--env-file','.env.elk','--env-file','.env.context','--env-file','.env.detection',
  '-f','compose.yaml','-f','compose.logging.yaml','-f','compose.context.yaml',
  '-f','compose.detection.yaml','-f','compose.llm.yaml')
docker compose @llmCompose up -d --build --no-deps llm-service
docker compose @llmCompose exec -T llm-service python -c "import os; print(bool(os.getenv('GEMINI_API_KEY','').strip()))"
Invoke-RestMethod http://127.0.0.1:8016/ready -TimeoutSec 5
```

Sau khi xác minh phạm vi dữ liệu và mọi gate, dùng `POST /analyze/trace` với header `X-Required-Provider: gemini`. Kiểm tra Single với `service_name=order` và Cross trên cùng trace. Dừng khi có lỗi. Ghi trạng thái, model thực tế, prompt version, event IDs, validation warnings, token usage và latency. Sau lượt smoke, tắt quyền external. `/ready` xác nhận cấu hình cục bộ, không thăm dò API Google.
