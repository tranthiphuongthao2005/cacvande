# Trạng thái 7A.6A

Gate collection hiện BLOCKED. Không có phê duyệt taxonomy/protocol thật, batch scope/budget, grouping/capture policy hoặc fault adapter approval. Gate dùng cùng hàm kiểm evidence với 7A.5I, bind candidate SHA-256 và hash proposal. Đầu vào governance do operator quản lý; tool kiểm phạm vi và toàn vẹn, không cấp quyền hoặc xác thực chữ ký operator.

`--require-ready` trả exit code 1 nếu cổng còn đóng. Không có entrypoint chạy live trong module này.

Có thể chuẩn bị nghiệm thu tiếp Normal A và Processing A với adapters giới hạn hiện có. Cascade A, Timeout A và Database A có evidence live lịch sử; Retry A có legacy scenario. Bốn slot thiếu bounded live adapter là Processing B, Cascade B, Timeout B và Retry B. Các slot khác chờ thiết kế/phạm vi/taxonomy. Cần config/campaign independence có tài liệu, quyết định policy PARTIAL/UNKNOWN, các adapter nghiệm thu, và phê duyệt mới cho từng batch. Còn 0 independently verified, 0 ground truth VERIFIED, 0 blind-eligible.

Regression PostgreSQL cô lập đạt 112 test trong 56,10 giây với 3 cảnh báo deprecation. 7 test mục tiêu đạt. Cờ require-ready trả exit code 1 trên batch Processing A còn chờ phê duyệt. Audit khớp 18 hash Processing A, 15 hash Normal A, 17/20/21 hash ba batch cũ và 63/63 fingerprint MeCoLog. Reviewer validator kiểm 13 references và 4 event, giữ NEEDS_REVIEW.

Chạy PowerShell tại thesis-log-anomaly.

```powershell
.\.venv\Scripts\python.exe -B -m tools.collection_readiness_7a6a --batch processing-a --audit
.\.venv\Scripts\python.exe -B -m tools.benchmark_readiness_7a5i
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_collection_7a6a.py
```
