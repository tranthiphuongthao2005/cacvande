# Readiness giai đoạn 7A

**Chưa sẵn sàng blind evaluation.** Audit ngoại tuyến rà 34 run và 34 trace ID. Không thấy trace ID hoặc event ID đã ghi bị trùng. Trong 130 bản ghi ứng dụng còn lưu, 31 bản ghi lịch sử thiếu event ID và 99 có ID. Năm run lịch sử thiếu file telemetry, nên event_count và service_count của chúng là null. Trùng ID và độc lập thực nghiệm là hai kiểm tra khác nhau.

| Nguồn | Run | Event còn quan sát được | Mục đích |
|---|---:|---:|---|
| Engineering history | 13 | 37 | Kiểm tra workflow, độ phủ và chất lượng instrumentation |
| Development đã kiểm chứng ELK | 7 | 31 | Đối chiếu API và dùng làm ví dụ minh họa |
| Pilot 3B | 14 | 62 | Kiểm tra thu thập, context và mức trùng |
| Đủ điều kiện evaluation | 0 | — | Cần cohort mới, sidecar chấm độc lập và manifest khóa |

Có 18 trace PARTIAL và 16 UNKNOWN, gồm UNKNOWN mặc định khi không có xác nhận Context. Trên lịch sử có 19 engineering receipts khớp oracle và 1 lệch oracle. Cả 14 pilot có lab oracle riêng, chưa phải nhãn nhân quả do reviewer độc lập xác nhận. Gộp cùng cơ chế lỗi, chữ ký tập template hoặc chuỗi template đã collapse cho bốn cụm bảo thủ kích thước 18, 6, 5, 5. Có 14 cụm chữ ký quan sát chính xác (service, message, status) lặp, gồm 28 run. Không có đủ chứng cứ độc lập thực nghiệm giữa bốn cụm vì workload còn tập trung vào cùng lab và trong khoảng 55 phút. Request payload không được lưu; chưa đo được trùng payload. Không dùng digest giả để lấp thiếu.

Bảng đầy đủ gồm scenario, run ID, trace ID, event/service count, completeness, nhãn hiện có, nhóm và eligibility. [CSV theo run](../experiments/benchmark_7a_audit.csv) · [Audit JSON](../experiments/benchmark_7a_audit.json) · [Schema rubric và ground truth](../experiments/benchmark_7a_schemas.json)

## Kiểm chứng ngoại tuyến

Regression đầy đủ đạt **53/53** (49,92 giây, ba cảnh báo deprecation có sẵn), gồm PostgreSQL lab riêng và bốn bài benchmark. Sau các thay đổi cuối ở validator và audit, chạy lại bốn fixture benchmark đều đạt. Fixtures kiểm tra hash, isolation, duplicate/campaign, pairing, citation đúng scope, failure, abstention, missing row, cluster bootstrap tái lập và CLI từ validate đến report. Kết quả fixture gắn nhãn FIXTURE_ONLY và không được dùng làm số liệu hiệu năng. Audit xác nhận **63 fingerprint MeCoLog**. Không mở HDFS final, không gọi LLM, không tạo notification.

```powershell
$stamp = Get-Date -Format yyyyMMdd_HHmmss
.\.venv\Scripts\python.exe -B -m tools.benchmark audit --output ".\experiments\benchmark_audit_$stamp.json" --csv ".\experiments\benchmark_audit_$stamp.csv"
.\.venv\Scripts\python.exe -B -m tools.benchmark schema --output ".\experiments\benchmark_schema_$stamp.json"
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_benchmark.py
.\.venv\Scripts\python.exe -B -m tools.audit_research
```

Khi có bundle đã khóa và nhãn adjudicated, chạy `tools.benchmark validate --manifest`, `aggregate --manifest --reviews --output` và `report --input --output`. Không có manifest evaluation đã khóa trong 7A. Chốt độc lập theo campaign và cơ chế, nhãn nhân quả đã rà soát, scope cố định và điều kiện provider/chi phí trước bất kỳ đánh giá thật nào.
