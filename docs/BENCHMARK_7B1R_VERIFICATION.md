# 7B.1R — Kiểm chứng offline

**DIAGNOSTICS_READY_ROOT_CAUSE_UNDETERMINED.**

| Hạng mục | Kết quả |
| --- | --- |
| Regression | 145 PASS, 10 skipped, 0 FAIL, 1 cảnh báo deprecation |
| Transport giả | Bao phủ HTTP 400, 401, 403, 404, 429, 500, 503, 504, DNS/connection dưới dạng ConnectError, timeout, schema rejection, malformed envelope/candidate và JSON hợp lệ |
| Privacy, retry và fallback | Fixture kiểm tra credential-bearing URL, Authorization, email và nhãn được giữ ngoài log/response. Một HTTP attempt mỗi lỗi, giữ public error contract và không fallback |
| Build | Image LLM riêng `thesis-log-anomaly-llm:7b1r-offline`; SDK 1.68.0 |
| Runtime offline | Container tạm tắt mạng, external off, cap 0, health 200 và ready 503 PROVIDER_NOT_CONFIGURED |
| Runtime lịch sử | Container LLM cũ và autoscale đều exited, giữ nguyên container cũ |
| Integrity | 8/8 frozen, 190/190 cohort, 95/95 acceptance, 88/88 historical, 63/63 fingerprints |
| API và ngân sách | 0 Gemini, 0 OpenAI, 0 evaluation calls, 0 USD |

Test serialization ban đầu kỳ vọng `thinkingLevel`. Mock transport trên SDK 1.68.0 cho thấy trường lồng là `thinkingConfig.thinking_level`. Đã sửa assertion theo request thực tế, giữ nguyên cấu hình adapter và chạy lại toàn bộ suite. Việc serialize thành công chỉ kiểm chứng SDK cục bộ. Lỗi lịch sử chưa có đủ dữ liệu để gán cho schema, cấu hình thinking, Google, hoặc lỗi mạng.

Hai file code đã sửa là `app/llm_provider.py` và `tests/test_gemini_provider.py`. Approval 002 và execution ledger lịch sử vẫn giữ FAILED_SMOKE. Không có approval 003. Các SHA-256 của hồ sơ gốc và kết quả được ghi trong [artifact diagnostics](../experiments/gemini_smoke_7b1/provider-diagnostics-002.json).

Operator chưa cần thao tác để hoàn thành 7B.1R. Image kiểm thử có thể được triển khai với external tắt khi khôi phục service. Việc thực hiện smoke mới cần phê duyệt riêng và không thuộc lượt này.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m tools.audit_research
```
