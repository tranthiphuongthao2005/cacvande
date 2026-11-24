# Kiểm chứng provider thật

**BLOCKED_MISSING_CREDENTIALS.** Process kiểm chứng thiếu cả `OPENAI_API_KEY` và `LLM_MODEL`. Lệnh preflight đã dừng với mã thoát 2 trước khi mở kết nối hoặc tạo artifact real. Do đó không xác minh được quyền truy cập API hoặc model. Không hiển thị giá trị credential.

| Mục | Kết quả |
|---|---|
| API calls OpenAI thật | 0 |
| Model OpenAI thật | Chưa cấu hình |
| Cặp Single/Cross thật | Chưa chạy |
| Evidence validation thật | Chưa xác minh |
| Token usage và latency OpenAI | Không có số đo |
| Chi phí OpenAI | Không phát sinh |

## Cấu hình và kiểm soát đã kiểm tra

Đã khảo sát abstraction, SDK pin, model qua environment, request schema strict, timeout, retry, xử lý lỗi và giới hạn đồng thời. SDK retry bằng 0; smoke verifier từ chối instance có retry hoặc ngân sách khác đúng hai lần gọi còn nguyên. Cần cờ đồng ý chi phí riêng trước khi chạy. Lỗi được trả bằng mã cấu trúc, không echo khóa, body từ provider hoặc input nhạy cảm. Readiness chỉ xác minh cấu hình cục bộ.

Schema bổ sung `provider_response_status` và readiness ghi tham số liên quan đến budget. Verifier mới kiểm tra ID trong đúng sự kiện và phạm vi, đối chiếu observation cấu trúc, kiểm tra abstention hoặc giả thuyết, checks, limitations, và sự hiện diện của warnings. Nội dung suy luận vẫn cần review thủ công. Kết quả real, nếu có, là một phép thử tích hợp, chưa đo Root Cause Accuracy.

## Regression và mock trên Compose

Pytest đạt **42/42** trong 46,31 giây với ba cảnh báo deprecation đã có. Bao phủ mock, provider timeout/error, ground-truth isolation, prompt injection và các chốt credentials, phê duyệt chi phí, ngân sách, retry. PostgreSQL lab riêng phục vụ các integration tests.

Compose vẫn chạy provider mock. Kiểm chứng lại cùng một trace cascade qua Context thật, Single giữ 3 event Order và Cross giữ 5 event. Cả hai trả `INSUFFICIENT_EVIDENCE` và metadata provider `mock`. Detection API vẫn trả HTTP 503 `NOT_READY_FOR_SCORING`; audit xác minh đủ 63 fingerprint. [Artifact mock 5B](../experiments/llm_5b_mock_verification.json)

File mới gồm `.env.example`, `tools/verify_real_llm.py` và tài liệu 5B. Cập nhật schema và readiness của LLM service, README, ignore rule và test preflight. [Cấu hình và lệnh PowerShell](REAL_LLM_SETUP.md)
