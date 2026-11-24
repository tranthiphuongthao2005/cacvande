# 7B.1R — Chẩn đoán lỗi Gemini

**ROOT_CAUSE_UNDETERMINED.** Ledger 002 ghi một POST Single Order, HTTP 502 `PROVIDER_ERROR`, 3.050,665 ms và một lượt bị trừ khỏi cap. Context hai mode trả 200 và khớp hash. Results rỗng. Container cũ có tám dòng lifecycle, không có traceback, upstream status hay chi tiết DNS/TLS. Bộ đếm runtime xác nhận lượt đi vào adapter, còn Google receipt là UNKNOWN. [Ledger](../experiments/gemini_smoke_7b1/gemini-smoke-7b1-002.execution.json)

Trong triển khai tại thời điểm sự cố, `GeminiProvider.generate` trả `PROVIDER_ERROR` ở nhánh SDK `APIError` sau khi loại các mã 429, 408 và 504, hoặc nhánh `httpx.HTTPError/ValueError`. `llm_api.analyze` chuyển `ProviderFailure` thành HTTP và mã public. Hai nhánh đó không giữ exception gốc trong log. Kiểm tra candidate và Pydantic đã có mã public riêng.

## Audit adapter

Image cũ xác nhận `google-genai==1.68.0`. Client nhận key từ cấu hình runtime, dùng Gemini Developer API `generativelanguage.googleapis.com/v1beta`, tắt proxy từ environment và redirect, timeout 20 giây, một attempt SDK. `generate_content` nhận model đã khóa, system instruction RCA, payload đã chuẩn bị, JSON MIME và Pydantic JSON Schema, tối đa 1.200 output tokens, một candidate, thinking MINIMAL và automatic function calling tắt. Adapter chỉ chấp nhận candidate STOP, validate JSON bằng `ModelAnalysis` và lấy prompt, candidate, thinking và total tokens từ usage metadata. Các thiết lập này giữ nguyên.

Google công bố model Gemini 3.1 Flash-Lite hỗ trợ structured output và Standard Free Tier có giá 0 USD cho văn bản. Schema của Gemini hỗ trợ một tập con JSON Schema. Mock transport kiểm tra serialization và contract cục bộ. Mức tương thích schema phía Google và quyền truy cập/quota project vẫn cần chứng cứ runtime riêng. [Model](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite) · [Structured output](https://ai.google.dev/gemini-api/docs/structured-output) · [Giá](https://ai.google.dev/gemini-api/docs/pricing) · [SDK](https://googleapis.github.io/python-genai/)

## Diagnostics nội bộ

`app/llm_provider.py` bổ sung structured warning gồm attempt ID, UTC, duration, model, stage, exception class, category, thông điệp cố định đã lọc, upstream HTTP status khi có HTTP response, provider status theo allowlist, receipt và retryability. Tin nhắn/body gốc chỉ được xét trong bộ nhớ để nhận diện lỗi schema hoặc model theo mẫu cụ thể. Các giá trị này, URL, headers, key, dữ liệu đầu vào và traceback không được ghi. HTTP 404 không chỉ rõ model được ghi UNKNOWN; HTTP 429 có thể do quota nên retryability để trống. Receipt CONFIRMED chỉ xác nhận đã thấy phản hồi ở tầng provider hoặc nhận được candidate để kiểm tra, chưa xác nhận generation thành công. Lỗi SDK decode thiếu metadata hoặc transport giữ UNKNOWN.

Các nhóm gồm auth, permission, model not found, invalid request, schema, rate limit, network, timeout, upstream, response parse và unknown. Public contract giữ `PROVIDER_ERROR`, `PROVIDER_TIMEOUT`, `PROVIDER_RATE_LIMITED`, `PROVIDER_NO_STRUCTURED_RESULT` và `INVALID_MODEL_OUTPUT` ở các nhánh tương ứng. Retry vẫn bằng 0.
