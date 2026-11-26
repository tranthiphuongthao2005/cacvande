# Incident Management API

API nội bộ Stage 9.6 chạy tại loopback, ví dụ `http://127.0.0.1:18017`. OpenAPI ở `/docs` và `/openapi.json`. `GET /health` kiểm liveness. `GET /ready` kiểm cấu hình, SQLite và trạng thái handoff nếu được bật.

## Authentication

Mọi route `/incidents` yêu cầu `Authorization: Bearer <token>`. Token operator có quyền đọc và chuyển trạng thái. Token reader tùy chọn có quyền đọc. Actor được lấy từ `INCIDENT_OPERATOR_ID` gắn với operator credential trên server. Cấu hình này biểu diễn một operator nội bộ và chưa hỗ trợ quản lý danh tính người dùng. Request không được khai actor. Token không dùng trong URL, log hoặc SQLite.

| Route | Kết quả |
| --- | --- |
| `GET /incidents` | `items`, `total`, `limit`, `offset` cho managed incidents. |
| `GET /incidents/statistics` | Nhóm count, creation trend UTC, resolution duration nếu có, metrics ingestion và queue nếu đã bật handoff. |
| `GET /incidents/{incident_id}` | Incident detail hiện tại, kèm lineage IDs, trace version, mock flag và record version. Nếu ID thuộc legacy scenario store, trả về legacy detail tương thích. |
| `GET /incidents/{incident_id}/timeline` | Các mốc thực tế, nguồn timestamp và trace version. |
| `GET /incidents/{incident_id}/evidence` | Evidence theo role, version và revision source ID. `observed=null` khi chỉ có ID từ Detection. |
| `GET /incidents/{incident_id}/revisions` | Lịch sử Detection, Context và Analysis với source ID, hash và thông tin xử lý. |
| `GET /incidents/{incident_id}/history` | Trạng thái trước/sau, actor, reason, changed time và record version. |
| `PATCH /incidents/{incident_id}/status` | Chuyển lifecycle của managed incident. |

List và statistics hỗ trợ `incident_status`, `analysis_status`, `severity`, `service`, `anomaly_type`, `detection_source`, `analysis_provider`, `is_mock`, `context_completeness`, `trace_id`, `source_namespace`, `from_time`, `to_time`. Service khớp observed hoặc affected. Bounds xét thời điểm tạo incident theo khoảng nửa mở và yêu cầu datetime có múi giờ. List sắp `last_detected_at DESC, incident_id ASC`. Offset có thể dịch giữa các trang khi có dữ liệu mới. Default limit 50, server giới hạn tối đa bằng `INCIDENT_MAX_PAGE_SIZE` và không vượt quá 200. Các list con nhận limit/offset.

Ví dụ status update.

```json
{"status":"INVESTIGATING","reason":"Operator started investigation","expected_version":1}
```

Các transition được phép gồm OPEN→INVESTIGATING, OPEN→RESOLVED, INVESTIGATING→RESOLVED, RESOLVED→CLOSED và RESOLVED→OPEN. CLOSED là terminal. Stage 9.6 không cấp quyền sửa evidence, analysis hoặc human verification qua PATCH. Response lỗi dùng `{"error":{"code":"..."}}`. 401/403 dành cho auth, 404 cho ID không tồn tại, 409 cho stale version hoặc transition sai, 413 cho body quá lớn, 422 cho validation và 503 cho storage hoặc readiness.

## Dashboard và đếm số liệu

Stage 10.1 có thể dùng list/detail, evidence, timeline và operations history. Stage 10.2 có thể dùng statistics với UTC range. Statistics đếm managed incident một lần theo incident ID; `detection_revision_count` có mẫu số riêng. Multi-label anomaly types hoặc service có thể đếm cùng incident ở nhiều nhóm. Mock count dựa trên cờ kết quả hiện tại và real count vẫn bằng 0 khi chỉ có mock. Resolution duration dùng thời gian tạo đến lần resolve đang có của các incident đủ timestamp. Legacy scenario giữ detail cũ và không được chuyển ngầm sang lifecycle/statistics mới.
