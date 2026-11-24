# Schema log ứng dụng

Index hàng ngày thesis-logs-YYYY.MM.DD được chọn từ timestamp sự kiện UTC. ILM xóa index sau 7 ngày tính từ lúc index được tạo. ES lưu nguyên JSON ứng dụng trong _source.app, đồng thời chuẩn hóa các trường được map để truy vấn. Mapping dynamic=false, app.enabled=false chỉ giữ app gốc trong _source và tránh lập index động.

| Trường Elasticsearch | Nguồn | Kiểu |
|---|---|---|
| @timestamp | app.timestamp, parse ISO 8601 | date_nanos |
| event_id | app.event_id, đồng thời là _id | keyword |
| service_name | app.service | keyword |
| trace_id, span_id, request_id | Trường cùng tên | keyword |
| level | app.level | keyword |
| message | app.event, mã sự kiện ổn định | text |
| endpoint | app.route, route template | keyword |
| http_method | app.method | keyword |
| status_code | app.status | integer |
| duration_ms | app.duration_ms | double |
| error_type | app.code | keyword |
| dependency_service | app.dependency | keyword |

Các trường chỉ có khi nguồn ghi chúng. Request ID là ID của SERVER span trong service đó và được giữ cho log phát sinh từ CLIENT span; Trace ID dùng để nối nhiều service. Mỗi log record cấp event_id một lần, cả stderr và file NDJSON dùng cùng ID và timestamp. OTel spans, access logs của Uvicorn và logs container Postgres/Elastic không nằm trong ba đường dẫn Filebeat.

Filebeat kiểm tra hình thức timestamp, trace/span/request/event IDs, service, level và tên sự kiện. Ingest pipeline từ chối field app lạ hoặc kiểu số không hợp lệ và parse thời gian. Không đưa request body, header, secret hoặc nhãn kịch bản vào logger. scenario_id không thuộc schema vì ground truth lưu ngoài luồng quan sát. Nếu hợp đồng thay đổi, cần cập nhật allowlist có chủ đích.

Filebeat dùng registry bền, file fingerprint và document ID ổn định. Routing theo ngày UTC từ timestamp nguồn giúp replay ghi lại cùng _id trong cùng index. Đây là cơ chế idempotency cho cùng sự kiện tại ES. Mỗi service giữ file hiện tại và tối đa ba bản xoay 5 MiB. Nếu collector dừng lâu hơn thời gian lưu file, các log cũ có thể mất do rotation. Log phát trước khi overlay bật không tự backfill từ Docker.

Overlay chạy một instance và một Uvicorn worker cho mỗi service. Nếu scale nhiều process/container, cấp file và volume riêng theo instance hoặc chuyển sang agent thu thập phù hợp. Nhiều process cùng xoay một file có thể làm mất log.
