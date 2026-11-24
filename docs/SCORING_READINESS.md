# Compatibility gate và trạng thái chấm điểm

**Trạng thái API: NOT_READY_FOR_SCORING.** Gate chia riêng kiểm tra cấu trúc, chẩn đoán biểu diễn và điều kiện phê duyệt protocol. Gate không dùng ngưỡng coverage/OOV tùy ý để tuyên bố hiệu quả phát hiện.

| Kiểm tra | Cách thực hiện |
|---|---|
| Parser coverage | So catalog và fallback trên cùng các observation thật, báo unknown và số template |
| OOV và tensor | So named/positional, giữ frozen vocabulary. Kiểm shape, dtype, finite và phạm vi ID |
| Session length | Histogram độ dài, số vị trí padding và event bị cắt ở window 50 |
| Checkpoint integrity | Băm checkpoint trước/sau và audit 63 fingerprint nghiên cứu |
| Tách support/query | Kiểm trace ID, event ID, nhóm và phân bố lớp. Snapshot partial chặn việc duyệt support |
| Ground truth isolation | Observation được validate theo DetectionSession, label sidecar được join ngoài luồng sinh feature |
| Reproducibility | Băm observation và label, xác minh assignment độc lập thứ tự input, dựng lại candidate tensor hai lần với cùng cache SBERT |

## Kết quả pilot

Thu 14 trace mới, hai lượt cho mỗi kịch bản. Có 2 Normal, 12 Anomaly, 62 event với ID duy nhất và 0 lượt bị loại. Anomaly có 6 trace dài ≤4 và 6 dài >4 trên toàn pilot. Histogram độ dài là 1:2, 3:2, 4:4, 5:4, 9:2. Có 638/700 vị trí padding (91,14%) và 0 event truncation.

| Biểu diễn | Sự kiện fallback hoặc unknown | Key OOV | Tensor |
|---|---:|---:|---|
| HDFS replay | 62/62 fallback | 58/58 | Đúng schema |
| Catalog dùng key có tên | 0/62 unknown | 58/58 | Đúng schema |
| Catalog dùng key vị trí | 0/62 unknown | 0/58 | Đúng schema |

Catalog có bảy template trên pilot. Không có mẫu số cho character OOV do tham số quan sát đều là số. Candidate tensors được dựng hai lần với cùng cache SBERT và khớp từng byte. Giảm OOV khi dùng `pos:1` chỉ xác nhận ID nằm trong vocabulary. Cần kiểm tra ảnh hưởng của ánh xạ này trên development độc lập trước khi dùng để chấm điểm.

Quy tắc gộp tạo bốn nhóm kích thước 8, 2, 2, 2. Chỉ một nhóm chứa Normal. Bản chia thử seed 123 có:

| Pool thử | Normal | Anomaly | Thành phần lỗi |
|---|---:|---:|---|
| Support | 2 | 2 | Database failure ×2 |
| Development | 0 | 2 | Processing failure ×2 |
| Evaluation | 0 | 8 | Timeout, Unavailable, Retry exhaustion, Cascading failure ×2 mỗi loại |

Đây là kết quả kiểm tra khả thi của split. Evaluation chưa được khóa. Support thử có 2 Anomaly ngắn và 0 Anomaly dài, và cả 14 snapshot được đánh dấu partial. Cả Single-Prototype và Length-Aware Multi-Prototype đều chưa đủ điều kiện triển khai.

Pytest đạt 26/26 trong 47,40 giây, gồm regression với PostgreSQL lab riêng. Ba cảnh báo deprecation thuộc Starlette và Drain gốc.

Checkpoint SHA-256 và 63 fingerprint nghiên cứu khớp. Sau khi collector phục hồi cấu hình thường, ba service trả HTTP 200 tại `/ready`; Detection vẫn trả 503. Không gọi MeCoLog forward, không train và không mở HDFS final. Xem [receipt thu thập](../experiments/micro_pilot_seed123/collection.json) và [báo cáo gate](../experiments/micro_compatibility_seed123.json).

## Tái lập

Từ `thesis-log-anomaly` với stack ELK, Detection API và key chỉ đọc đã cấu hình. Dùng thư mục và tên báo cáo mới để giữ nguyên pilot.

```powershell
$stamp = Get-Date -Format yyyyMMdd_HHmmss
$dataset = ".\experiments\micro_pilot_$stamp"
$ml = '..\tuanmartin-MeCoLog-8c446ac\.venv\Lib\site-packages'
.\.venv\Scripts\python.exe -B -m tools.collect_micro_dataset --output $dataset --repetitions 2 --seed 123
.\.venv\Scripts\python.exe -B -m tools.check_micro_compatibility --dataset $dataset --features --ml-site-packages $ml --output ".\experiments\micro_compatibility_$stamp.json"
.\.venv\Scripts\python.exe -B -m tools.audit_research
curl.exe -sS http://127.0.0.1:8014/ready
```
