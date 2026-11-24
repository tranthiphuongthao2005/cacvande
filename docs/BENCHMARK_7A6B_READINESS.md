# Readiness 7A.6B

Collector dùng chung có check ngay tại POST boundary. Gate thiếu hoặc bị chặn, mô phỏng, sai campaign/config/output/cap, hết hạn hay dùng lại đều không dispatch. Không live test. Hiện chưa có governance thật và batch authorization, 0 độc lập xác minh, 0 VERIFIED ground truth, 0 blind eligible. Cần operator duyệt taxonomy/protocol, cohort grouping và policy completeness, ký authorization mới và chứng minh adapter deadline/rollback. Timeout A, Database A và Cascade A còn cần chuyển adapter legacy sang đường gated. Reviewer cần phân công thật và xác thực nhãn. Benchmark tiếp tục đóng.

MOCK_VERIFIED cho số POST khi gate từ chối. FIXTURE_VERIFIED cho code wiring, replay qua tiến trình mới và reviewer intake. LIVE_VERIFIED chỉ áp dụng cho evidence Normal A và Processing A đã lưu trước gate này. Gate 7A.6B chưa có nghiệm thu live.

Regression đầy đủ 124 test đạt trong 69,88 giây trên PostgreSQL cô lập, với 3 cảnh báo deprecation. Lần đầu dừng ở khởi tạo vì cluster còn recovery; lần sau chờ readiness dài hơn và hoàn tất. 12 test mục tiêu đạt. Audit khớp 18 hash Processing A, 15 hash Normal A, 17/20/21 hash ba batch, 33 pilot, 9 review 7A.2 và 4 mỗi smoke cũ. MeCoLog khớp 63/63. Reviewer packet giữ NEEDS_REVIEW với 13 tham chiếu và 4 event. 0 POST nghiệp vụ, fault live hoặc lượt OpenAI.

```powershell
.\.venv\Scripts\python.exe -B -m tools.collection_readiness_7a6a --batch processing-a --audit
.\.venv\Scripts\python.exe -B -m tools.cohort_review_7a6b cohort
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_collection_7a6b.py tests/test_telemetry_receipts.py
```
