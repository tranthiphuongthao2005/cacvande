# Readiness 7A.5A

Thiết kế 7 nhóm, 14 slot, trong đó 6 đường chạy đã có và 8 DESIGN_BLOCKED. Có 0 cấu hình độc lập được xác minh, 0 trace thu mới, 0 VERIFIED, 7 packet chờ review, 0 blind-eligible. Trần kế hoạch 28 trace; trần trước audit với sáu đường chạy hiện tại là 12. Protocol là draft chờ duyệt và khóa. Không có lượt OpenAI hoặc request tới stack nghiệp vụ trong giai đoạn này.

Blocker gồm cơ chế/đường chạy đủ khác biệt cho tám slot, adapter collection có cap được duyệt, reviewer độc lập và nhãn, cohort chưa phơi bày, model snapshot, token preflight, bảng giá, phê duyệt chi phí và khóa protocol. Filebeat handoff vẫn UNCONFIRMED. MeCoLog không tham gia đánh giá này và trạng thái scoring lưu trước đó vẫn NOT_READY_FOR_SCORING.

Kiểm tra offline đi qua cohort, diversity ở mức thiết kế, separation, reviewer packet, isolation, pairing, cost cap và checksum lịch sử. Hash ba batch 17/20/21; pilot 33, 7A.2 9, hai smoke 4 mỗi bộ; MeCoLog 63/63.

Regression trên PostgreSQL lab cô lập đạt 77/77 trong 44,29 giây, với ba cảnh báo deprecation. Lần khởi chạy đầu gặp giới hạn token Windows của pg_ctl. Khởi động postgres trực tiếp và dùng role sẵn có của cluster test đã giải quyết lỗi setup.

Thiết kế kế thừa kiểm toán từ BENCHMARK_7A4_CONSOLIDATED_REPORT.md và BENCHMARK_7A4R_READINESS.md, quy mô từ BENCHMARK_SAMPLE_SIZE_PLAN.md, blocker từ LLM_EVALUATION_READINESS.md, cùng quy tắc từ PAIRED_EVALUATION.md, LLM_EVALUATION_RUBRIC.md và HUMAN_REVIEW_WORKFLOW.md. Công cụ sử dụng để đối chiếu gồm tools.consolidate_7a4, tools.audit_research và validator cặp hiện có. Các giới hạn collector được rà từ tools.collect_benchmark_7a4 và experiments/run_scenario.py.

```powershell
.\.venv\Scripts\python.exe -B -m tools.validate_7a5
.\.venv\Scripts\python.exe -B -m tools.audit_research
```

Lệnh dùng từ thư mục thesis-log-anomaly. Regression đầy đủ dùng TEST_PG_ADMIN_URL trỏ PostgreSQL cô lập, sau đó chạy .venv/Scripts/python.exe -B -m pytest -q.
