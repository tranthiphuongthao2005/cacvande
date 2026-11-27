# Context API

| Endpoint | Hành vi |
|---|---|
| GET /health | 200 khi process hoạt động |
| GET /ready | Kiểm tra mở PIT bằng chính credential của service |
| GET /context/trace/{trace_id} | Exact trace. Mode mặc định là cross_service |

`mode=single_service` yêu cầu `service_name=user|product|order`. Với cross_service, bỏ service_name. `wait_ms` nhận 0–3000 để polling, ngoài timeout riêng của từng lệnh Elasticsearch. Trace ID phải là 32 ký tự hex thường và khác zero. Lỗi có cấu trúc gồm 422 input/scope, 404 không có trace trong phạm vi, 502 ES response sai hình thức, 503 kết nối hoặc cấu hình và 504 timeout khi chưa có kết quả.

Response gồm `trace_id`, `mode`, `selected_service`, `services`, `start_time`, `end_time`, `event_count`, `events`, `timeline`, `dependencies`, `evidence_event_ids`, `completeness_status`, `retrieval_warnings` và `data_quality`. Mỗi event trả ID, timestamp, service, trace, span, level, message, status và dependency/error nếu quan sát được. Status bên caller trong dependency record mang ý nghĩa status mà caller ghi nhận. Timeline phân biệt nó với status của server đích trong log completion. Event ID chỉ tham chiếu bằng chứng quan sát.

## PowerShell

Vào thư mục thesis-log-anomaly và bảo đảm ELK đang chạy:

```powershell
if (-not (Test-Path .env.context)) {
    .\.venv\Scripts\python.exe -B -m tools.init_context_env
}
docker compose --env-file .env.elk --env-file .env.context -f compose.yaml -f compose.logging.yaml -f compose.context.yaml up -d --build --no-deps context-service
$trace = '09b71700f5dca84ec31f133b92b2ba91'
$api = 'http://127.0.0.1:8015'
Invoke-RestMethod "$api/ready"
Invoke-RestMethod "$api/context/trace/$($trace)?mode=cross_service&wait_ms=550"
Invoke-RestMethod "$api/context/trace/$($trace)?mode=single_service&service_name=product"
```

Trace minh họa chỉ dùng được trong retention. Nếu hết hạn, dùng trace mới đã lưu receipt từ verifier ELK.
