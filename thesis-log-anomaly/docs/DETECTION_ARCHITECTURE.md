# Kiến trúc Detection API

`app/trace_store.py` truy vấn exact term `trace_id` trong `thesis-logs-*` và chỉ lấy trường quan sát được từ log ứng dụng. Nó dùng PIT, phân trang `search_after`, tối đa 4.096 hit đọc vào và 2.048 event giữ lại. Snapshot có cửa sổ truy vấn tám ngày để bao phủ retention bảy ngày. Event trùng ID và trùng payload được gộp. Event trùng ID nhưng lệch payload bị từ chối. Thứ tự là UTC timestamp rồi event ID. `_shard_doc` phân biệt hit vật lý khi phân trang. [Tài liệu Elasticsearch về PIT và phân trang](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/paginate-search-results.html)

DetectionSession v1 giữ trace ID ở cấp session và giữ service, event ID, span ID, timestamp, level, event name và HTTP status trên từng event. Session ID là SHA-256 từ môi trường, phiên bản sessionization và trace ID. Với một bản ghi POST /orders kết thúc, Order là ứng viên service gốc. Trường hợp khác dùng `unknown`. Mọi snapshot từ log được đánh dấu `partial` vì chưa có bằng chứng span gốc, watermark và số event kỳ vọng. `dropped_events` chỉ đếm các event duy nhất đã thấy và bị cắt khỏi contract. Bản ghi đến trễ có thể xuất hiện khi truy vấn lại.

| Endpoint | Input | Trạng thái trực tiếp |
|---|---|---|
| GET /health | — | 200 khi tiến trình hoạt động |
| GET /ready | — | 503 `NOT_READY_FOR_SCORING`, kèm trạng thái cấu hình kết nối |
| POST /detect/session | DetectionSession v1 | 503 cùng định danh, số event và cảnh báo |
| POST /detect/trace | JSON có `trace_id` | 503 sau khi lấy được trace, 404 khi không tìm thấy |

Lỗi định dạng trả 422 và chỉ chứa mã lỗi. ES lỗi kết nối trả 503. Dữ liệu trace xung đột hoặc sai schema trả 502. Phản hồi sẵn sàng trong thiết kế gồm `trace_id`, `session_id`, `model_version`, `support_protocol_id`, `scoring_method`, `anomaly_score`, `predicted_label`, `threshold`, `event_count`, `preprocessing_warnings`, `evidence_event_ids` và `processing_time_ms`. Evidence IDs chỉ tham chiếu event đầu vào. API chỉ có thể bật đường chấm điểm khi ứng dụng được khởi tạo với một runtime đã duyệt. Compose hiện chỉ khởi tạo phần adapter, dùng 192 MiB, 0,5 CPU, filesystem chỉ đọc và UID 10001. Checkpoint và snapshot SBERT nằm ngoài Docker image.

## Chạy bằng PowerShell

Từ `thesis-log-anomaly`, giả định Elasticsearch của giai đoạn 2 đã sẵn sàng trên loopback. Key giới hạn quyền đọc `thesis-logs-*` và hết hạn sau 30 ngày. File credential nằm ngoài Git và Docker build context. Overlay giữ API 8011–8013 và stack ELK. Detection bind vào 127.0.0.1:8014.

```powershell
if (-not (Test-Path .env.detection)) {
    .\.venv\Scripts\python.exe -B -m tools.init_detection_env
}
docker compose --env-file .env.elk --env-file .env.detection -f compose.yaml -f compose.logging.yaml -f compose.detection.yaml up -d --build --no-deps detection-service
curl.exe -sS http://127.0.0.1:8014/health
curl.exe -sS http://127.0.0.1:8014/ready
$body = @{trace_id='09b71700f5dca84ec31f133b92b2ba91'} | ConvertTo-Json -Compress
$body | curl.exe -sS -H 'Content-Type: application/json' --data-binary '@-' http://127.0.0.1:8014/detect/trace
```

Trace ví dụ phụ thuộc retention. Khi trace hết hạn, chạy lại verifier ELK với output mới và dùng Trace ID mới.
