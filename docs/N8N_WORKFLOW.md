# Workflow scenario incident

Export ở `workflows/scenario-incident.json`. Bốn node gồm Scenario Webhook (Webhook 2.1), Orchestrate and Persist Incident (HTTP Request 4.2), Return Workflow Result và Return Transport Error (Respond to Webhook 1.4). URL upstream cố định. Node HTTP timeout 58 giây, không retry. Adapter timeout 25 giây mỗi request và tối đa hai lượt đang xử lý. Contract n8n trả lại status từ adapter; transport failure riêng trả 502.

POST `/webhook/scenario-incident` với Bearer token. Payload có `trace_id`, `analysis_mode`, `service_name` nếu single và đúng một trong `request_id` hoặc `idempotency_key`. Chỉ các trường này được chấp nhận, ground truth bị từ chối. Cùng key và scope trả lại incident đã lưu, không gọi downstream. Trường context_calls và llm_calls vẫn mô tả lượt gốc, còn replayed mô tả request hiện tại.

| Workflow status | Nguồn | HTTP | Local notification |
|---|---|---:|---|
| COMPLETED | LLM ANALYZED và qua validation | 200 | Có thể lưu một đề mục review |
| INSUFFICIENT_EVIDENCE | LLM abstention hợp lệ | 200 | Suppressed |
| VALIDATION_FAILED | Schema, scope hoặc evidence sai | 502 | Suppressed |
| PROVIDER_UNAVAILABLE | Provider, budget, rate limit hoặc transport LLM | 503 | Suppressed |
| CONTEXT_UNAVAILABLE | Context thiếu hoặc không truy cập được | 503 | Suppressed |
| TIMEOUT | Downstream timeout hoặc HTTP 504 | 504 | Suppressed |
| INTERNAL_ERROR | Lỗi chưa ánh xạ | 500 | Suppressed |

Response report lưu observations đã đối chiếu, suspected cause nếu có, evidence IDs, limitations, next checks và warnings. LLM free-text chưa xác minh vẫn là giả thuyết cần review.
