# Stage 9.1 — Rule-based anomaly detection

`POST /detect/rule-based` dùng Elasticsearch PIT snapshot từ `ContextStore`. Detection Service dùng cùng ES client và API key như TraceStore của MeCoLog. Engine chuẩn hóa các trường allowlist, bỏ trùng, loại toàn bộ bản sao có cùng ID nhưng nội dung mâu thuẫn, rồi sắp xếp theo timestamp và ID trước khi áp dụng bộ luật `1.0.0`. `/detect/trace`, `/detect/session` và readiness hiện có giữ contract MeCoLog, gồm `NOT_READY_FOR_SCORING` khi thiếu approved runtime.

## Field mapping

| Elasticsearch | Structured log ở producer | Cách dùng |
| --- | --- | --- |
| `@timestamp`, `event_id`, `trace_id`, `service_name` | `timestamp`, `event_id`, `trace_id`, `service` | Thứ tự log, kiểm tra bằng chứng, khớp trace và service |
| `request_id`, `span_id` | Cùng tên | Gắn các event phía Order với cùng request. Span ID được xác thực nếu có, chưa có parent span ID trong mapping này. |
| `message`, `level` | `event`, `level` | Tên event chuẩn và mức log |
| `status_code`, `error_type`, `dependency_service` | `status`, `code`, `dependency` | HTTP completion và lỗi dependency có kiểu |
| `endpoint`, `http_method` | `route`, `method` | Xác định hướng gọi của chuỗi R07 |

Evidence ID phải là ID hex thường 32 ký tự, khác ID toàn số 0 và thuộc đúng trace. Engine bỏ qua ground truth, fault activation và mọi field ngoài allowlist. Chỉ phát evidence ID có thật trong snapshot sau validation.

## Luật

| Luật | Điều kiện và phạm vi |
| --- | --- |
| R01 `HTTP_SERVER_ERROR` | `request_completed` với HTTP 500–599. Status ghi ở retry event là status do caller quy đổi. HTTP 5xx chỉ xác nhận kết quả lỗi. |
| R02 `REQUEST_TIMEOUT` | `dependency_attempt_failed` hoặc `dependency_exhausted` có `error_type=dependency_timeout`. Một retry sau đó thành công vẫn có thể chứa timeout đã quan sát. |
| R03 `DATABASE_FAILURE` | `database_connection_failed`. Telemetry hiện bảo đảm lỗi kết nối repository, chưa phân loại crash hoặc các kiểu lỗi thao tác DB khác. |
| R04 `PROCESSING_FAILURE` | `order_processing_failed` hoặc cặp `request_failed/internal_error`. |
| R05 `DEPENDENCY_UNAVAILABLE` | `dependency_exhausted/dependency_unavailable` với dependency đã biết. Retry tạm thời rồi thành công không tự kích hoạt luật này. |
| R06 `RETRY_EXHAUSTED` | Event `dependency_exhausted`, có thể đồng thời khớp R02 hoặc R05. |
| R07 `CASCADE_FAILURE` | **PARTIAL**. Yêu cầu một GET downstream của service mà Order gọi, HTTP 502/503, nằm trong cửa sổ của lần thử cuối. Sau đó quan sát Order attempt lỗi, exhaustion và POST `/orders` trả 502. Ba event Order phải cùng request ID. Nhiều candidate downstream, thiếu mắt xích, timestamp hòa hoặc snapshot có lỗi chất lượng có thể khiến luật không khớp. Chuỗi là dấu hiệu lan truyền. Mapping log thiếu parent span nên chưa chứng minh quan hệ nhân quả. |
| R08 `ERROR_EVENT` | ERROR hoặc CRITICAL chưa được luật cụ thể nào dùng làm bằng chứng. Filebeat hiện chỉ tiếp nhận danh sách event producer đã định nghĩa, nên phạm vi fallback bị giới hạn theo ingestion. |

Severity là nhãn quy ước. Evidence CRITICAL cho `critical`, nhóm R01/R03–R07 cho `high`, các match còn lại cho `medium`. Affected services là service phát event bằng chứng. Dependency chỉ được suy ra là service bị ảnh hưởng khi có event của chính service đó trong chuỗi bằng chứng.

## API

Request JSON.

```json
{"trace_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
```

Ví dụ HTTP 200 cho completion trả 503.

Log input tương ứng sau Elasticsearch ingest.

```json
{"@timestamp":"2026-11-26T07:59:59Z","event_id":"00000000000000000000000000000005","trace_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","service_name":"order","message":"request_completed","level":"ERROR","status_code":503,"endpoint":"/orders","http_method":"POST"}
```

```json
{
  "detection_id": "a1d3c5e7a1d3c5e7a1d3c5e7a1d3c5e7",
  "trace_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "detection_source": "rule_based",
  "detection_status": "ANOMALY",
  "is_anomaly": true,
  "matched_rules": [
    {"rule_id": "R01", "anomaly_type": "HTTP_SERVER_ERROR",
     "evidence_event_ids": ["00000000000000000000000000000005"]}
  ],
  "anomaly_types": ["HTTP_SERVER_ERROR"],
  "severity": "high",
  "observed_services": ["order"],
  "affected_services": ["order"],
  "evidence_event_ids": ["00000000000000000000000000000005"],
  "context_completeness": "partial",
  "detection_timestamp": "2026-11-26T08:00:00Z",
  "latency_ms": 2.1,
  "rule_version": "1.0.0",
  "model_score": null,
  "diagnostics": []
}
```

HTTP 200 cũng áp dụng cho `NO_ANOMALY_DETECTED` và `INSUFFICIENT_DATA`. Kết luận không phát hiện bất thường yêu cầu outcome hợp lệ trong snapshot và đủ dữ liệu để đánh giá các event đã quan sát. Snapshot rỗng, bị cắt, có log lỗi hoặc thiếu outcome dẫn đến `INSUFFICIENT_DATA` nếu chưa có bằng chứng dương hợp lệ. Giá trị `is_anomaly` là `null` với `INSUFFICIENT_DATA` và `DETECTION_ERROR`. Nonempty snapshot có nhãn `partial` vì truy vấn log chưa chứng minh trace đầy đủ. ID của lần gọi, timestamp và latency thay đổi giữa các lần gọi.

HTTP 422 dùng error envelope của Detection API. HTTP 502 cho search response sai cấu trúc, 503 cho store chưa cấu hình hoặc không khả dụng và 504 cho timeout hoặc search không hoàn chỉnh. Các lỗi backend dùng schema `DetectionResult` với diagnostic code cố định, không đưa lỗi raw hay credential vào response và log. Log hoàn tất có JSON fields phục vụ tra cứu theo `detection_id`. ES client dùng timeout 10 giây mỗi thao tác I/O và snapshot giới hạn tối đa 512 hàng, với một hàng bổ sung để phát hiện cắt dữ liệu. Đây là giới hạn theo thao tác và số trang, chưa có deadline độc lập cho toàn request.

## Chạy và kiểm thử

Từ worktree riêng trong PowerShell.

```powershell
$python = "..\thesis-log-anomaly\.venv\Scripts\python.exe"
& $python -B -m tools.check_stage_9_1_integrity
& $python -B -m pytest -q -p no:cacheprovider tests/test_rule_detection.py tests/test_detection.py tests/test_context.py tests/test_api.py tests/test_contract.py tests/test_logging_file.py tests/test_integration.py
```

Để chạy service, cấp `DETECTION_ES_URL` và `DETECTION_ES_API_KEY` qua môi trường PowerShell với Elasticsearch của stack cô lập. Dùng cổng loopback riêng sau khi kiểm tra cổng còn trống.

```powershell
& $python -m uvicorn app.detection_api:app --host 127.0.0.1 --port 18014 --no-access-log
# Trong một PowerShell khác, thay trace ID bằng trace của stack cô lập.
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:18014/detect/rule-based' `
  -ContentType 'application/json' -Body '{"trace_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
```

OpenAPI có tại `/docs`. Bộ test dùng fixture tự tạo và HTTP transport giả đi qua FastAPI, ContextStore và phân trang PIT. Kết quả theo nhóm gồm 31 unit PASS, 10 API integration PASS, 21 regression PASS và 10 PostgreSQL integration SKIP vì môi trường offline không cấp `TEST_PG_ADMIN_URL`. Không có Docker/Elasticsearch live test trong giai đoạn này. Gemini, OpenAI và live fault injection đều bằng 0.

Stage 9.2 có thể gọi endpoint qua schema versioned sau khi có yêu cầu riêng. Router cần giữ nguyên trạng thái chưa đủ dữ liệu hoặc lỗi backend và readiness guard của nhánh MeCoLog.
