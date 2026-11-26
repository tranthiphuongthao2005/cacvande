# 7B.1S — Kết quả smoke Gemini

**FAILED_SMOKE.** Không chạy lại hoặc tính vào benchmark.

| Chế độ | Events | Completeness | Kết quả |
| --- | ---: | --- | --- |
| Single Order | 3 | UNKNOWN | POST trả HTTP 502 PROVIDER_ERROR sau 1.717,698 ms. Diagnostics xác nhận HTTP 503 UNAVAILABLE từ upstream, exception ServerError, stage upstream_response, receipt CONFIRMED và retryable=true. Không có response model, JSON, tokens, finish reason hay response ID. |
| Cross | 5 | PARTIAL | NOT_ATTEMPTED do Single thất bại. |

Một generation attempt được ghi và runtime counter giảm còn một call. Counter này không đo lường hóa đơn hoặc nội dung generation được tính phí. Diagnostics ghi HTTP upstream 503 nên có xác nhận response tại tầng upstream, dù không có generation output. Retry, OpenAI và evaluation đều 0. Ước tính chi phí Free Tier là 0 USD. Lượt smoke không cho biết nguyên nhân bên trong dịch vụ upstream ngoài mã UNAVAILABLE.

Cleanup PASS. Container thoát mã 0, OOMKilled=false, restart count 0, log cho thấy shutdown sạch và port 8016 từ chối kết nối. External calls hiện không khả dụng. Autoscale demo vẫn stopped. Approval 003 được đóng và không được tái sử dụng.

Integrity PASS: 8/8 frozen, 190/190 cohort, 95/95 acceptance, 88/88 historical, 63/63 MeCoLog. Historical approvals 001/002 khớp checksum đã ghi. Formal benchmark giữ nguyên trạng thái khóa.

| Attempt | Category | HTTP upstream | Provider code | Receipt | Retryable | Latency |
| --- | --- | ---: | --- | --- | --- | ---: |
| `26da11423bea4331a8b854aa3d073df1` | PROVIDER_UPSTREAM_ERROR | 503 | UNAVAILABLE | CONFIRMED | true | 1.149,303 ms ở provider call; tổng API 1.717,698 ms |

Artifacts: [approval](../experiments/gemini_smoke_7b1/gemini-smoke-7b1-003.json), [activation](../experiments/gemini_smoke_7b1/gemini-smoke-7b1-003.activation.json), [execution và cleanup](../experiments/gemini_smoke_7b1/gemini-smoke-7b1-003.execution.json), [results](../experiments/gemini_smoke_7b1/gemini-smoke-7b1-003.results.json). Results file rỗng vì không có response model nào được kiểm định.
