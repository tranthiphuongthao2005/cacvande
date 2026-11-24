# Readiness 7A.5D

Hai chiều taxonomy và protocol v2 đang ở draft. 9 đường kỹ thuật có điều kiện, 5 slot loại/chặn, 0 cấu hình độc lập, 5 packet đủ evidence để xem xét, 2 thiếu activation độc lập, 0 VERIFIED và 0 blind-eligible. Cohort chưa thu.

LLM readiness chưa đạt. Prompt đề xuất rca-evidence-v1, model snapshot và decoding chưa khóa. Biến OPENAI_API_KEY và LLM_MODEL không hiện diện trong shell kiểm tra; trạng thái provider deployment và hiệu lực credential chưa kiểm chứng. Không gọi OpenAI. Kế hoạch 8.192 input token và 800 output token mỗi call cần kiểm số token thực gồm prompt/schema. Với 34 lượt, trần danh nghĩa 278.528 input và 27.200 output token; cost ceiling và bảng giá chưa duyệt. Trước khi chạy cần khóa pairing và tách quyền truy cập label.

Operator cần duyệt taxonomy, rubric v2, phân công reviewer, grouping, ngân sách cohort, live adapter, cutoff snapshot và chính sách incomplete, model/decoding/token/cost ceiling. Danh sách trong operator_decisions_pending.json. Chưa khóa protocol hoặc cho phép collect/provider.

Regression cô lập đạt 103 test trong 53,42 giây với 3 cảnh báo deprecation. Validator xác nhận 15/15 hash smoke, ba batch 17/20/21 hash, 33 hash pilot, 9 hash 7A.2, 4 hash mỗi smoke 7A.3 và 7A.3B, cùng 63/63 fingerprint MeCoLog. Dry-run Normal A ghi 0 request.

```powershell
.\.venv\Scripts\python.exe -B -m tools.validate_7a5d
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a5c --campaign normal-a
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_benchmark_7a5d.py
```

Chạy từ thesis-log-anomaly. Với regression đầy đủ, chạy pytest -q trong môi trường TEST_PG_ADMIN_URL trỏ PostgreSQL cô lập.
