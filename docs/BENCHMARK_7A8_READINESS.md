# Benchmark lock readiness 7A.8

WAITING_INDEPENDENT_REVIEW, benchmark_locked=false. Formal split vẫn BLOCKED_PROTOCOL_MISMATCH nếu áp nguyên điều kiện giữ family gần trùng một split. Scope exploratory candidate giữ nguyên. Collection integrity, pairing và inference isolation đạt. Ground truth, grouping, eligibility, xử lý overlap và phê duyệt manifest chưa đạt. Dossier đủ review 10, VERIFIED labels 0, verified independent groups 0, blind-eligible 0.

Runtime tối giản ổn định 40/40 khi thu. Sau restore full stack User/Product timeout 4 giây, Order/Context 200. Regression riêng có 130 PASS, 1 FAIL do Product lookup timeout trước processing hook; INTERMITTENT_UNRESOLVED. Hai live Processing 500 và hashes còn nguyên. Trong protocol candidate/hash đã duyệt và lock schema đã rà, không thấy điều khoản runtime bắt buộc full pytest PASS trước lock. Ghi nguyên failure và không miễn điều kiện nào. Chưa chạy lại test trong lượt audit này.

Evaluation manifest ứng viên có 10 records, không phải manifest khóa. Inference manifest chứa duy nhất case_id và hai path/hash, không label, group hoặc cấu hình. Ground truth manifest và decision templates tách khỏi inference. Cutoff theo contract 420 giây và không có monotonic timestamp riêng trong bundle.

Trước 7B, lấy quyết định reviewer thật, xác minh grouping và overlap/split, chốt phạm vi held-out execution hoặc exploratory, phê duyệt manifest/scoring và kiểm đủ điều kiện lock. Sau đó mới xem xét model snapshot, credentials, cost và quyền chạy riêng. Chưa gọi OpenAI.

```powershell
.\.venv\Scripts\python.exe -B -m tools.audit_benchmark_7a8
.\.venv\Scripts\python.exe -B -m tools.audit_benchmark_7a8 --require-lock-ready
```

Lệnh thứ hai cố ý trả exit khác 0 ở trạng thái hiện tại. Công cụ audit không khóa benchmark; cần tích hợp các quyết định thật trước khi có lock authorizer.
