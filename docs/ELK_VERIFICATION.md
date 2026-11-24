# Kiểm chứng logging tập trung

## Môi trường và phạm vi

Docker Desktop chạy Linux container trên Windows qua WSL2. Docker VM có 4 CPU và 5,79 GiB RAM. Máy Windows có 12 CPU logic, 7,68 GiB RAM vật lý và khoảng 60,42 GiB dung lượng trống trước khi tải image. Docker dùng driver json-file. Elasticsearch và Kibana chỉ lắng nghe ở cổng 9200 và 5601 trên loopback. User, Product và Order giữ cổng 8011, 8012 và 8013. Ba PostgreSQL chỉ dùng cổng 5432 trong mạng Compose. Filebeat không mở cổng trên host.

## Kiểm thử và tính toàn vẹn

Pytest chạy 15 bài, gồm 14 bài giai đoạn 1 và một bài mới đối chiếu bản sao stderr với NDJSON. Kết quả 15 đạt trong 39,50 giây với một cảnh báo deprecation Starlette/AnyIO. Nhóm database integration chạy với PostgreSQL 16 riêng; nhóm trace và fault chạy trên HTTP thật.

Audit checksum trước và sau triển khai khớp 63 file nghiên cứu, gồm 9 file Python gốc. Frozen protocol SHA-256 vẫn là `308e29ba2c48ff92c4ea3230206c99194daeb1e85a5832088c5b635c8285c63b`. Audit chỉ băm bytes của các artifact được bảo vệ.

## Kết quả Docker Compose

Elasticsearch báo `green`, Kibana báo `available`, và Filebeat qua healthcheck. Elasticsearch trả 401 khi truy cập thiếu xác thực. Kibana đã tạo data view `thesis-logs`. Ba PostgreSQL báo healthy, ba API trả 200 tại `/ready` sau khi runner phục hồi cấu hình thường.

| Kịch bản | HTTP | App events trong Docker | App events trong ES |
|---|---:|---:|---:|
| normal | 201 | 3 | 3 |
| timeout | 504 | 5 | 5 |
| unavailable | 503 | 1 | 1 |
| database | 503 | 4 | 4 |
| processing | 500 | 4 | 4 |
| retry | 502 | 9 | 9 |
| cascade | 502 | 5 | 5 |
| Tổng | | 31 | 31 |

Đối chiếu đủ 31 event theo document ID, payload JSON, timestamp, Trace ID, Span ID và Request ID. Kiểm tra lại số lượng theo từng trace sau cả suite cho 0 event thiếu và 0 event trùng. Có 35 bản ghi telemetry khác liên quan đến các trace trong Docker, nằm ngoài tập app events được index. Truy vấn toàn index tại thời điểm kiểm chứng trả 178 event User, 49 Product và 43 Order, gồm các lượt chuẩn bị và healthcheck. Bộ lọc đồng thời `level: ERROR` và status từ 500 trở lên trả 15 event. Không thấy trường ground truth trong các bản ghi app được đối chiếu.

Trace cascade là `09b71700f5dca84ec31f133b92b2ba91`. Cùng trace có User 200, Product 503 và Order 502. Retry ghi đúng ba lần thất bại và timeout có mã `dependency_timeout`. Chi tiết theo trace nằm trong [artifact kiểm chứng](../experiments/elk_verification.json).

## Tài nguyên quan sát

Ảnh chụp `docker stats --no-stream` trong lúc chạy suite. CPU là giá trị tức thời do Docker báo, RAM là mức tại thời điểm đo.

| Container | CPU | RAM đo được | Giới hạn RAM |
|---|---:|---:|---:|
| Elasticsearch | 51,59% | 745,3 MiB | 1.152 MiB |
| Kibana | 17,88% | 531,3 MiB | 896 MiB |
| Filebeat | 0,96% | 92,59 MiB | 160 MiB |

## File triển khai

| Nhóm | File |
|---|---|
| Compose và ingest | `compose.logging.yaml`, `logging/bootstrap.py`, `logging/filebeat.yml` |
| Ứng dụng và scenario | `app/telemetry.py`, `app/api.py`, `experiments/run_scenario.py` |
| Công cụ và test | `tools/init_elk_env.py`, `tools/verify_elk.py`, `tests/test_logging_file.py` |
| Tài liệu | `README.md`, `docs/ELK_SETUP.md`, `docs/LOG_SCHEMA.md`, `docs/ELK_VERIFICATION.md`, `docs/LOG_TO_SESSION_DESIGN.md` |
| Phạm vi credential | `.gitignore`, `.dockerignore` |

## Sự cố khởi động

- Elasticsearch khởi động chậm và lần bootstrap đầu hết thời gian chờ HTTP. Lệnh cài cấu hình có thể chạy lại với cùng volume. Timeout riêng cho bootstrap tăng từ 15 lên 90 giây.
- Filebeat từ chối hàng đợi 512 event khi kích thước lô mặc định lớn hơn hàng đợi. Cấu hình đặt giới hạn lô 128.
- Một bản ghi health ban đầu đến Elasticsearch trước khi có cấu hình pipeline ở đầu vào Filebeat. Bản ghi được chuẩn hóa lại qua pipeline theo đúng document ID, giữ nguyên payload nguồn. Event sau cấu hình dùng timestamp ứng dụng với độ chính xác microsecond.
- Kibana có độ trễ khi migration index nội bộ lần đầu. Trạng thái địa chỉ TCP và trạng thái ứng dụng cần được kiểm tra riêng.
- Lượt chạy normal đầu trả 504 khi User mất 653–1.080 ms để hoàn thành hai lượt lookup, vượt ngân sách 500 ms của Order. Overlay ELK đặt ngân sách lab lên 2 giây cho Order và Product cùng lúc. Product fault mode vẫn cố ý trì hoãn hơn ngân sách 250 ms. Giữ bản ghi lượt 504 để theo dõi biến động tài nguyên.

## Giới hạn

Đây là một stack đơn node cho lab, với HTTP và xác thực trên loopback và mạng Compose riêng. Đối chiếu theo trace phục vụ các scenario đã chạy. Log source có giới hạn rotation, nên collector dừng quá lâu có thể bỏ lỡ file đã bị luân chuyển. Elasticsearch giữ log 7 ngày. Thiết kế DetectionSession có quy tắc xử lý trace thiếu trong tài liệu riêng.
