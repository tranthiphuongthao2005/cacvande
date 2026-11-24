# 7B.1 — Hồ sơ chờ phê duyệt smoke Gemini

Trạng thái **PENDING_OPERATOR_APPROVAL**. Hồ sơ này chưa cấp quyền thực thi.

| Trường | Giá trị |
| --- | --- |
| Project | Dự án Gemini 2 |
| Billing tier | Free Tier, theo xác nhận của người vận hành |
| Provider và model | Gemini Developer API, `gemini-3.1-flash-lite` |
| Quota hoạt động | Chờ bằng chứng đã che thông tin nhạy cảm từ Rate Limits và Usage của project mới |
| ID phê duyệt (`LLM_GEMINI_SMOKE_APPROVAL_ID`) | Chờ người vận hành |
| Hết hạn UTC (`LLM_GEMINI_SMOKE_EXPIRES_UTC`) | Chờ người vận hành. Gate yêu cầu còn hiệu lực và cách thời điểm chạy tối đa một giờ |
| Trace đã rà soát (`LLM_GEMINI_SMOKE_TRACE_ID`) | Chờ trace ngoài cohort và xác nhận phạm vi dữ liệu |
| Xác nhận tier (`LLM_GEMINI_FREE_TIER_CONFIRMED`) | Chờ hoàn tất đối chiếu quota và tier trước khi đặt `1` |
| Phạm vi dự kiến | 1 Single-Service (Order), 1 Cross-Service trên cùng trace |
| Trần | 2 lượt Gemini, 0 retry, 0 USD, 0 OpenAI, 0 evaluation |
| SHA-256 của freeze index 7A.8R | `6f4e45bdbf11a6a26c6ec5210377366795208020d35066a2be5dc1b81fd36b49` |

Trước khi xin phê duyệt, đối chiếu trace ID với inference manifest đã khóa, rà soát dữ liệu đầu vào sau bước `prepare` và xác nhận payload chỉ gồm dữ liệu smoke phi nhạy cảm. Ưu tiên dữ liệu tổng hợp. Tránh logs chứa dữ liệu cá nhân, bí mật hoặc nội dung nội bộ chưa được phép chia sẻ. [Điều khoản Gemini API](https://ai.google.dev/gemini-api/terms)
