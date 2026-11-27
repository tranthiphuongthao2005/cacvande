# Context API completeness v2

Endpoint mới `GET /context/v2/trace/{trace_id}` dùng lại query/scope của v1. Response chứa `schema_version`, `context` (payload v1), `completeness` và `completeness_provenance`. V1 giữ nguyên schema và cách phân loại. V2 đọc bundle theo trace chỉ từ đường dẫn read-only do operator mount. SHA-256 phát hiện khác biệt nội dung và ràng buộc seal/receipt. Nó không thay thế ACL của host hay chữ ký producer. Không có endpoint ghi receipt từ client.

Classifier tách request completed, source sealed, ingestion reconciled và trace complete. Với thiếu seal/receipt, provenance bị lỗi hoặc snapshot hiện tại lệch ID/content, v2 trả cảnh báo và giữ phân loại v1. `request_completed=false` trong v2 nghĩa là chưa xác minh được qua receipt, không kết luận request chưa từng kết thúc. Single chỉ xác nhận event thuộc scope service và không nâng completeness toàn trace. Trường `AUTHORITATIVE_CLOSED_CAPTURE` dành cho nguồn tin cậy có kiểm kê đầy đủ. Smoke collector không phát hành loại đó. Nhánh COMPLETE được kiểm thử bằng fixture, chưa có proof authoritative thật để kích hoạt.

```powershell
docker compose --env-file .env.elk --env-file .env.context -f compose.yaml -f compose.logging.yaml -f compose.context.yaml -f compose.receipts.yaml up -d --build --no-deps context-service
$trace = (Get-Content .\experiments\benchmark_7a3_smoke\smoke.json -Raw | ConvertFrom-Json).trace_id
Invoke-RestMethod "http://127.0.0.1:8015/context/trace/$trace"
Invoke-RestMethod "http://127.0.0.1:8015/context/v2/trace/$trace"
Invoke-RestMethod "http://127.0.0.1:8015/context/v2/trace/$($trace)?mode=single_service&service_name=order"
```

Đã đối chiếu response v1/v2 thật với cùng trace. [Artifact tích hợp Docker](../experiments/benchmark_7a3_integration_verification.json)
