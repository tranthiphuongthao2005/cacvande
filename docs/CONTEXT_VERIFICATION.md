# Kiểm chứng Context Service

Context Service healthy trên Docker Compose, cổng loopback 8015. GET /health và /ready đều trả 200. Tại thời điểm đo, container dùng 39,59 MiB trên giới hạn 192 MiB, CPU 0,28%. Elasticsearch, Kibana, Filebeat, Detection và ba PostgreSQL vẫn healthy. Detection API trả 503 `NOT_READY_FOR_SCORING`.

| Kiểm tra | Kết quả |
|---|---|
| Pytest | 32/32 trong 36,23 giây, gồm PostgreSQL lab riêng; ba cảnh báo deprecation có sẵn |
| Bảy trace kiểm chứng ELK | 31/31 event ID khớp exact query Elasticsearch; 6 PARTIAL, 1 UNKNOWN |
| Pilot 3B | 62/62 event ID khớp receipt observation; 12 PARTIAL, 2 UNKNOWN |
| Mapping và schema | Các field và kiểu khớp index thực. Ground truth không có trong payload kiểm tra |
| Audit MeCoLog | 63 SHA-256 khớp, frozen protocol giữ nguyên |

## Cascade minh họa

Trace `09b71700f5dca84ec31f133b92b2ba91` trả năm event ở cross-service. Timeline có User 200, Product 503, Order báo dependency attempt failed/exhausted, và Order hoàn thành với 502. Cạnh Order → Product có source là event `dependency_attempt_failed`. User 200 là quan sát server; liên kết Order → User chưa được xác minh từ index. Cross-service là PARTIAL. Trong ba truy vấn single-service, User có một event, Product một event và Order ba event; mỗi tập ID đúng bằng tập index theo service. Single-service Product trả `services=["product"]`, `event_count=1`, status HTTP quan sát 503 và completeness UNKNOWN.

Cascade có 3 snapshot với `wait_ms=550`, không có thay đổi qua các poll, conflict, missing span ID hoặc timestamp tie. Warnings gồm `DEPENDENCY_LINKS_UNVERIFIED`, `ORDER_COMPLETION_OBSERVED` và `ROOT_SPAN_OR_INGESTION_WATERMARK_UNVERIFIED`. Completeness vẫn bị giới hạn bởi parent span ID, watermark và dependency success evidence. [Artifact JSON có response đầy đủ](../experiments/context_verification.json)

## File và tái lập

- Service và schema: `app/context_api.py`, `app/context_store.py`, `app/incident_context.py`.
- Triển khai: `compose.context.yaml`, `services/context/Dockerfile`, `tools/init_context_env.py`.
- Kiểm thử: `tests/test_context.py`, `tools/verify_context.py`, `experiments/context_verification.json`.
- Cập nhật README, .gitignore và bốn tài liệu Context.

Sau khi chạy Compose theo [hướng dẫn API](CONTEXT_API.md), dùng đường dẫn artifact mới:

```powershell
$stamp = Get-Date -Format yyyyMMdd_HHmmss
.\.venv\Scripts\python.exe -B -m tools.verify_context --output ".\experiments\context_verification_$stamp.json"
.\.venv\Scripts\python.exe -B -m tools.audit_research
```

Verifier cần trace cũ còn retention, Detection ở 8014, Context ở 8015 và metadata mapping từ ELK local. Test fixture bao phủ duplicate, timestamp trùng, lỗi thiếu service/span, timeout, lọc scope, polling update và điều kiện COMPLETE nội bộ. LLM, n8n và scoring nằm ngoài runtime Context.
