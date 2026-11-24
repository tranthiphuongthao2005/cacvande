# Kiểm chứng giai đoạn 3

**Trạng thái: `NOT_READY_FOR_SCORING`.** Đã kiểm chứng adapter, khung API và strict-load checkpoint. Biểu diễn log mới có thể tạo tensor đúng schema, nhưng chưa có căn cứ để coi nó tương thích với luồng suy luận HDFS. Chưa có support protocol Microservices đã khóa. Do cả hai điều kiện này, không gắn runtime vào service và không gọi MeCoLog forward. Không có anomaly score hoặc prediction thực nghiệm.

## Docker và truy vấn thật

| Trace theo scenario | Event quan sát được | HTTP từ Detection API |
|---|---:|---:|
| Normal | 3 | 503 |
| Timeout | 5 | 503 |
| Unavailable | 1 | 503 |
| Database failure | 4 | 503 |
| Processing failure | 4 | 503 |
| Retry failure | 9 | 503 |
| Cascading failure | 5 | 503 |
| Tổng | 31 | |

Cả bảy phản hồi lấy được trace từ Elasticsearch bằng key chỉ đọc và giữ danh sách ID duy nhất. Cascade `09b71700f5dca84ec31f133b92b2ba91` chứa User, Product và Order. `/health` trả 200, `/ready` trả 503. Docker stats ghi một lần 44,56 MiB trên giới hạn 192 MiB và CPU 2,97%. ELK, ba API và ba PostgreSQL tiếp tục chạy. Bộ kiểm tra chỉ dùng Trace ID và số event từ artifact giai đoạn 2, còn ground truth nằm ngoài luồng.

Bằng chứng gồm [trace adapter](../experiments/detection_trace_verification.json), [HTTP thật](../experiments/detection_api_verification.json) và [tensor ứng viên](../experiments/detection_feature_verification.json). Chạy lại verifier theo lệnh PowerShell bên dưới tạo JSON tensor chẩn đoán khớp từng byte với artifact đã lưu.

## Test, checkpoint và blocker

- Pytest **23/23** trong 38,20 giây với ba cảnh báo deprecation từ Starlette và Drain gốc. Chạy PostgreSQL 16 riêng tại 55439 cho regression integration. Các test mới bao phủ exact query, PIT, dedup, timestamp, API contract, padding, truncation, OOV, checkpoint checksum, inference context với stub, prototype và leakage.
- Audit trước và sau xác minh 63 fingerprint. Frozen protocol SHA-256 `308e29ba2c48ff92c4ea3230206c99194daeb1e85a5832088c5b635c8285c63b`. Kết quả strict-load là 32 tensor, eval mode, 0 tensor tham số còn bật gradient.
- 3.962 raw training lines replay đúng Drain. Adapter ứng viên tạo đủ năm tensor hữu hạn. 31/31 event dùng fallback, 29/29 key OOV, không có mẫu số character OOV, 319/350 vị trí padding và 0 event truncation. Các thống kê là thuộc tính của biểu diễn ứng viên trên bảy trace lab.
- Blocker: chưa xác minh domain mapping từ event cấu trúc sang raw Content và chưa có ba pool độc lập có nguồn nhãn hợp lệ. Các số liệu trên chưa đánh giá khả năng phát hiện bất thường.

## File mới và cập nhật

- Service: `compose.detection.yaml`, `services/detection/Dockerfile`, `app/detection_api.py`, `app/trace_store.py`.
- Chẩn đoán và scorer: `app/mecolog_runtime.py`, `app/prototypes.py`, `tools/init_detection_env.py`, `tools/verify_detection.py`, `tests/test_detection.py`.
- Kết quả: ba JSON detection verification trong `experiments/`. Cập nhật `README.md`, `.gitignore` và tạo năm tài liệu Detection.

## Tái lập bằng PowerShell

Chạy từ `thesis-log-anomaly` sau khi khởi động overlay và tạo key theo [hướng dẫn](DETECTION_ARCHITECTURE.md). Venv nghiên cứu hiện thiếu httpx, nên lệnh dùng venv dịch vụ làm môi trường chính rồi bổ sung đường dẫn dependency ML của venv nghiên cứu. Chỉ dùng venv nghiên cứu cùng phiên bản Python. Verifier không đọc nhãn HDFS final.

```powershell
.\.venv\Scripts\python.exe -B -m tools.audit_research
$ml = '..\tuanmartin-MeCoLog-8c446ac\.venv\Lib\site-packages'
$stamp = Get-Date -Format yyyyMMdd_HHmmss
.\.venv\Scripts\python.exe -B -m tools.verify_detection --features --ml-site-packages $ml --output ".\experiments\detection_repeat_$stamp.json"
$env:TEST_PG_ADMIN_URL = 'postgresql://lab@127.0.0.1:55439/postgres'
.\.venv\Scripts\python.exe -B -m pytest -q
Remove-Item Env:TEST_PG_ADMIN_URL
```

Suite đầy đủ cần PostgreSQL lab đang chạy trên cổng cấu hình. Khi các trace cũ hết retention, tạo receipt mới bằng verifier ELK và truyền đường dẫn đó qua `--receipt`.
