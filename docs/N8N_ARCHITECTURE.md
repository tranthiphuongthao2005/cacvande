# Kiến trúc điều phối sự cố

Webhook scenario chạy trên n8n loopback. Workflow chuyển payload và Bearer token tới incident-adapter riêng trong mạng Compose. Adapter xác thực, validate, claim idempotency, gọi Context, kiểm tra bằng chứng, gọi LLM, xác minh report và lưu incident. Node cuối trả status HTTP. Adapter chịu trách nhiệm transaction và các quy tắc trạng thái để dùng chung với kiểm thử Python.

n8n dùng volume riêng lưu workflow và tài khoản owner. Incident-adapter dùng SQLite trên volume riêng, UID 10001, không mở port host. SQLite giữ digest của request key, signature scope, incident ID và báo cáo tối thiểu. Không lưu header, body gốc, log raw, nhãn hoặc secrets. TTL 7 ngày tính từ lúc claim, dọn theo lượt claim mới. Transaction đảm bảo cùng key và scope chỉ sinh một incident. Dùng lại key với scope khác trả 409. Pending do lỗi tiến trình giữ tới TTL để tránh replay tự phát. GET nội bộ theo incident ID cần cùng token.

LLM API nhận header nội bộ `X-Required-Provider: mock` từ adapter. Nếu runtime khác mock hoặc chưa cấu hình, request dừng trước khi lấy context và trước generation. Không fallback provider. LLM vẫn tự fetch Context theo contract Phase 5, nên với một lượt thành công có một GET trực tiếp từ adapter và một GET nội bộ từ LLM.

Notification là local sink lưu trong cùng transaction với report. Chỉ `COMPLETED` có thể tạo một entry cần review, tối đa một entry mỗi trace/scope trong một giờ. Entry tách observations, suspected cause, evidence IDs, limitations và recommended checks. `INSUFFICIENT_EVIDENCE` và lỗi được lưu với cờ review, không ghi notification. Không có external destination hoặc hành động remediation.

## Interface detection cho tương lai

Anomaly event sẽ cần event ID/idempotency key, trace ID, thời điểm, model version, protocol ID và kết quả có provenance. Consumer phải kiểm tra Detection readiness, rằng threshold và support protocol đã được duyệt, cùng provenance của prediction thật. Sau đó mới cho phép định tuyến sang Context và LLM theo chính sách riêng. Giai đoạn này chỉ publish webhook scenario.
