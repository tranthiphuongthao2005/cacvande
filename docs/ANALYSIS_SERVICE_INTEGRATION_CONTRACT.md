# Snapshot-preserving Analysis HTTP contract

Stage 9.5 dùng `POST /analyze/package` tại Mock Analysis Service. Lớp tích hợp đọc một Context Package đã commit và gửi đúng Context payload qua n8n. Contract tích hợp `1.0` này độc lập với LLM benchmark contract.

## Request

| Field | Ý nghĩa |
| --- | --- |
| `schema_version` | `1.0` |
| `analysis_job_id`, `idempotency_key` | Cùng SHA-256 của JSON array gồm namespace nguồn, package ID, trace version, contract version và mục đích `incident-analysis-mock`. |
| `context_package_id`, `trace_id`, `trace_version` | Identity của đúng phiên bản package. |
| `context_mode` | `cross_service` |
| `context_payload` | Schema Stage 9.4 `incident-context-v1`. Inline JSON, không có URL/path do client cung cấp. |
| `context_payload_sha256` | SHA-256 của đúng JSON payload theo canonicalization Stage 9.4. |

Canonicalization dùng UTF-8, key sắp xếp, separator compact, giữ thứ tự array, không escape Unicode hoặc chấp nhận NaN. Adapter kiểm SHA-256 từ cả JSON đến và payload đã validate. Nó đối chiếu envelope với chính package của job trong SQLite và recheck readiness trước khi bắt đầu phân tích. Đổi payload cho cùng idempotency key trả 409. Payload quá giới hạn trả 413. POST cần `Authorization: Bearer <isolated-token>`; token không thuộc JSON envelope. Mock chỉ đọc Context từ request và không truy xuất Elasticsearch hoặc gọi Context API.

## Response

HTTP 200 chỉ trả một kết quả đã commit. Response lặp lại binding gồm schema version, job ID, package ID, trace ID/version, payload hash và idempotency key. Mock thêm `analysis_provider="mock"`, `analysis_mode="MOCK"`, `is_mock=true`, `analysis_status`, `evidence_validation_scope` và `observations`. `SIMULATED_OBSERVATIONS` là mô phỏng quan sát có thể đối chiếu. `INSUFFICIENT_EVIDENCE` là abstention hợp lệ với danh sách rỗng. Mỗi observation có `event_id`, `service_name`, `kind` và `status_code`. Adapter đối chiếu ID, event type, service, status và tín hiệu dependency với chính payload đã xác minh. Scope `CONTEXT_ID_AND_OBSERVABLE_FIELDS` giới hạn xác minh ở dữ liệu quan sát. Contract không có trường root cause, confidence, token usage hoặc API cost.

HTTP 202 báo cùng key đã bắt đầu nhưng chưa có kết quả; 401 là thiếu hoặc sai auth; 409 là binding/state conflict; 422 là schema, hash hoặc evidence validation failure. HTTP 503 hoặc 504 có thể báo phân tích hoặc storage lỗi. Kết quả thành công đã commit là nguồn xác thực kể cả khi webhook mất acknowledgement. Trạng thái bất định cần đối chiếu theo key cũ, không cấp key mới để gửi lại.

## Ranh giới với LLM và Stage 9.6

Người phụ trách LLM cần triển khai hoặc phê duyệt một HTTP adapter riêng tiếp nhận package đã validate, bảo toàn hash/identity và abstention. `POST /analyze/trace` hiện tự fetch Context và vì vậy không bảo toàn snapshot này. Tách operational envelope khỏi prompt input. Phần evidence được phép phân tích là `context_payload`. Trace lineage, idempotency, retry và workflow IDs ở tầng vận hành. Detection rule là tín hiệu điều phối. Không thêm ground truth, expected root cause hoặc activation metadata.

Stage 9.6 có thể đọc `workflow_incident_handoff`, đối chiếu `response_sha256`, nguồn và cờ mock, nhóm analysis revisions theo `incident_correlation_key`, và dùng trace version để giữ lịch sử. `superseded=1` chỉ bản lịch sử, kể cả khi kết quả tới sau khi version mới đã xuất hiện. Một khóa correlation hiện đại diện cho namespace và trace, không tự tạo incident độc lập theo từng version. Mock metrics không thuộc LLM evaluation.
