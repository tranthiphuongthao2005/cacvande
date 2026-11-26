# 7B.1S — Kế hoạch recovery Gemini

**PENDING_OPERATOR_APPROVAL.** Approval 001 và 002 đã đóng. 002 giữ FAILED_SMOKE, một attempt và Google receipt UNKNOWN. Kế hoạch dùng cùng trace Cascade A ngoài cohort và image có diagnostics.

## Kiểm chứng trước activation

- Image cục bộ `thesis-log-anomaly-llm:7b1r-offline`, digest `sha256:c40033666786d26e30c6814b55328e1eda46ab24d9859168025a5693f30873b4`. Sáu file app trong image tắt mạng khớp SHA-256 workspace. SDK `google-genai==1.68.0`.
- Dùng lại 145 PASS, 10 SKIP, 0 FAIL của 7B.1R. Mười case thuộc `tests/test_integration.py` dùng fixture yêu cầu `TEST_PG_ADMIN_URL` cho PostgreSQL cô lập. Chúng kiểm tra database và luồng microservice. Kiểm chứng Gemini serialization, canonical output, evidence, zero retry và zero fallback dùng transport giả riêng. Không chạy lại regression suite trong lượt này.
- Prompt `rca-evidence-v1`, cả hai schema, settings và hai snapshot được bind trong approval. Kiểm tra mẫu credential trong adapter, API và JSON smoke không thấy literal key. Log lịch sử không chứa exception payload; diagnostics log dùng metadata cho phép và thông báo cố định đã qua test redaction.
- Script UTF-8 BOM parse bằng Windows PowerShell 5.1. Kiểm tra riêng phần validation không có Docker/HTTP đã chặn hồ sơ pending, chấp nhận fixture phạm vi đúng, và chặn fixture SDK retry hoặc TPM thiếu. Fixture chỉ nằm trong bộ nhớ. Activation record chưa được tạo.

## Trình tự sau khi được phê duyệt

1. Operator cấp phê duyệt riêng cho 003 và ghi quota mới của đúng Free Tier project/model cùng timestamp UTC. Giữ external off cho đến khi chạy script từ PowerShell đang giữ key. Script pin image theo digest, chỉ recreate LLM, ghi activation độc quyền và dừng LLM nếu activation thất bại. Quota phải còn mới trong 30 phút tại activation; activation có hiệu lực 30 phút.
2. Đối chiếu activation, approval, digest runtime, container ID/start time/restart count, expiry, call cap 2 và calls remaining 2. Kiểm tra hai GET Context, mỗi mode một lần. Single Order có 3 event UNKNOWN, Cross có 5 event PARTIAL. Kiểm tra event IDs, hash payload, thông tin nhạy cảm và trace ngoài cohort. Dừng trước generation khi một gate thất bại.
3. Ghi attempt trước POST Single với `X-Required-Provider: gemini`. Technical PASS yêu cầu response thật, canonical schema, evidence validation và kiểm tra model/token metadata khả dụng. Sau Single PASS, chờ ít nhất 10 giây, xác minh identity, expiry, calls remaining và quota rồi gọi Cross cùng trace. Zero retry/fallback. Dừng Cross nếu Single thất bại.
4. Khi lỗi, lấy structured diagnostic trước recreate hoặc xóa container. Ghi attempt ID, stage, exception class, sanitized message, upstream HTTP/status code, model, UTC, duration, receipt và retryability. Phân biệt lỗi serialization/schema và response parse dựa trên stage cùng metadata; khi thiếu bằng chứng để UNKNOWN. Runtime counter chỉ đo lượt bị trừ cục bộ.
5. Ghi kết quả, đóng external gate, xác minh cleanup rồi audit 8/190/95/88/63. Không ghi smoke vào benchmark accuracy và không mở khóa formal benchmark. Nếu lỗi, giữ logs và ledger, đóng approval và không tái sử dụng.

[Approval 003](../experiments/gemini_smoke_7b1/gemini-smoke-7b1-003.json) · [Script activation](../tools/activate_gemini_smoke_7b1_003.ps1) · [Kiểm chứng 7B.1R](BENCHMARK_7B1R_VERIFICATION.md)
