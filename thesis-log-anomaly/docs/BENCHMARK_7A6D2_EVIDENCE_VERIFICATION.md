# Evidence verification 7A.6D.2

Năm template khớp cấu hình/campaign, cap một POST, zero retry và output chưa tồn tại. Kiểm offline cả readiness gate lẫn PostGate xác nhận 5/5 PENDING bị chặn, không tạo output reservation hoặc ledger. Không có activation, POST nghiệp vụ, API OpenAI, snapshot mới hay reviewer verdict.

Bản nháp normal-a.operator-draft.pending.json nhận ID và expiry dự kiến mới. Readiness check --require-ready trả exit code 1. PostGate cũng từ chối. Không có output reservation hay approval consumption cho lượt này.

Sau tuyên bố operator bổ sung, hồ sơ thật được ghi ở experiments/benchmark_7a5/normal_a_operator_governance_7a6d2. Sáu JSON evidence có decision ID riêng, operator_id local-project-operator, timestamp UTC, scope và hash tài liệu/proposal. File normal-a.approved.json giữ các binding do gate yêu cầu. File grouping và file capture riêng được tham chiếu trong mục grouping_and_capture_policy. Readiness gate đạt đủ năm checks và PostGate chấp nhận scope. Không sửa template.

Audit chỉ đọc khớp 18 hash Processing A lịch sử, 15 hash Normal A, 17/20/21 ba batch, 33 pilot, 9 review 7A.2, 4 cho mỗi smoke cũ và 63/63 fingerprint MeCoLog. Reviewer packet 13 tham chiếu và 4 event vẫn NEEDS_REVIEW. Regression hậu acceptance chưa áp dụng vì không có lượt live. Baseline gần nhất 131 pytest từ 7A.6D.1.

Normal A live đã qua kiểm toán sau cutoff. Producer/Docker/ES khớp 3/3/3, cả ba producer FLUSHED, không missing, duplicate, unexpected hoặc late trong phạm vi capture. Receipt khớp snapshot; Order projection đúng, label isolation đạt. Filebeat handoff UNCONFIRMED và TRACE_COMPLETE=false. Postflight PASS, fault/scope trống, runtime marker đã gỡ. Ledger khớp campaign, output và governance SHA-256 với approval ID đã dùng. Manifest bao phủ và xác minh 19/19 file. Audit lịch sử và 63 fingerprint đã chạy lại. Không chạy lại regression ở lượt này.

Lượt bốn adapter còn lại tạo governance riêng dưới experiments/benchmark_7a5/<configuration>_operator_governance_7a6d2. Mọi hash tham chiếu và bốn approval ID riêng đều khớp. User readiness dừng Processing A trước activation. Không có live bundle mới hay approval tiêu thụ mới. Kiểm lại bản Normal A 19/19, receipt/pair và ledger cùng audit lịch sử/63 fingerprint.

Regression sau khi chuỗi dừng đạt 131 PASS, 0 FAIL trên PostgreSQL cô lập, 3 cảnh báo deprecation trong 65,40 giây.

Lượt ổn định runtime dùng bốn approval gốc còn hạn. Kiểm integrity sau từng batch trước khi chuyển tiếp, và kiểm toán lại năm bundle sau khi hoàn tất. 95/95 hash, năm ledger record và năm receipt/pair khớp. 21 event cho mỗi nguồn trên năm run, 18 event từ bốn run mới. Single đúng projection Order của Cross; kết quả phân loại receipt khớp provenance lưu. Không có ground truth trong context. Filebeat handoff UNCONFIRMED và TRACE_COMPLETE=false ở cả năm lượt. Audit lịch sử và 63/63 fingerprint MeCoLog khớp.

Regression cuối đạt 131 PASS, 0 FAIL trên PostgreSQL cô lập trong 56,10 giây, 3 cảnh báo deprecation. Event IDs không giao nhau giữa năm acceptance bundle.

```powershell
.\.venv\Scripts\python.exe -B -m tools.collection_readiness_7a6a --batch normal-a --audit
.\.venv\Scripts\python.exe -B -m tools.audit_research
```
