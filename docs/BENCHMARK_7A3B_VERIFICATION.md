# Kiểm chứng 7A.3B

Smoke dùng hai request application. GET lấy tham chiếu lab từ một Order đã có, POST đo một Order mới với trace `52e1f3694e4f9be48205033e516864bf`. Kiểm listener bằng TCP, không dùng HTTP probe vào microservices trong ngân sách smoke. Overlay accounting được gỡ sau thu, ba service dùng lại môi trường bình thường. Không xóa volumes.

| Bằng chứng thật | Kết quả |
|---|---:|
| Producer ledger | 3 event, User/Product/Order mỗi service 1 |
| Docker / Elasticsearch | 3 / 3 event, đúng tập ID và nội dung |
| Missing / unexpected / duplicate | 0 / 0 / 0 |
| Flush | 3/3 event có cả stderr và file thành công, 0 failure |
| Late khi inspect sau seal | 0 |
| ACK Filebeat từng event | 0 |
| Context trước → sau receipt | Cross PARTIAL → PARTIAL, Single UNKNOWN → UNKNOWN |

Fixture an toàn kiểm tra missing/duplicate, delayed ingestion và event sau seal, không chủ động làm mất log trong runtime. [Reconciliation](../experiments/benchmark_7a3b_smoke/reconciliation.json) · [Accounting](../experiments/benchmark_7a3b_smoke/accounting.json) · [Docker integration](../experiments/benchmark_7a3b_integration_verification.json)

Regression đạt **69/69 pytest** trong 47,07 giây với ba cảnh báo deprecation có sẵn, gồm PostgreSQL lab riêng và bốn test mới. Artifact Docker xác nhận payload v1 giữ nguyên bên trong v2, provenance accounting hiện diện và receipt v2 của smoke 7A.3 vẫn truy xuất được.

Thêm `app/producer_accounting.py`, hai Compose overlay, tool smoke, unit tests và bốn tài liệu. Cập nhật `app/telemetry.py`, `app/telemetry_receipts.py`, `app/context_api.py` và README.

```powershell
.\.venv\Scripts\python.exe -B -m tools.smoke_producer_accounting
$stamp = Get-Date -Format yyyyMMdd_HHmmss
$out = "./experiments/benchmark_7a3b_smoke_$stamp"
.\.venv\Scripts\python.exe -B -m tools.smoke_producer_accounting --execute-local --output $out
$env:PRODUCER_RECEIPTS_DIR = "$out/receipts"
docker compose --env-file .env.elk --env-file .env.context -f compose.yaml -f compose.logging.yaml -f compose.context.yaml -f compose.receipts.yaml -f compose.producer-receipts.yaml up -d --build --no-deps context-service
$trace = (Get-Content "$out/reconciliation.json" -Raw | ConvertFrom-Json).trace_id
Invoke-RestMethod "http://127.0.0.1:8015/context/v2/trace/$trace"
.\.venv\Scripts\python.exe -B -m tools.audit_research
```

Smoke cần một Order lab đã có với User/Product còn hợp lệ. Nếu GET rỗng, tool dừng trước POST. Receipt mount mặc định trỏ tới smoke đã kiểm chứng.
