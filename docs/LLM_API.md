# LLM Analysis API

| Endpoint | Hành vi |
|---|---|
| GET /health | HTTP 200 khi process chạy |
| GET /ready | Provider đã cấu hình cục bộ hoặc HTTP 503, không gọi provider |
| POST /analyze/trace | Chỉ nhận `trace_id`, `mode`, `service_name` và `analysis_config_id` |
| GET /analysis/{analysis_id} | Đọc báo cáo trong RAM hoặc HTTP 404 |

Cross-service là mặc định và bỏ service_name. Single-service yêu cầu user, product hoặc order. Config ID mặc định `rca-v1`. Validation lỗi trả 422 không echo body. HTTP 404 khi Context không có trace, 429 khi hết ngân sách hoặc hết slot, 502 khi provider/context/output không hợp lệ, 503 nếu provider chưa cấu hình và 504 khi timeout.

IncidentAnalysis trả ID, trace, scope, provider, model được cấu hình và model provider trả về, prompt/config version, completeness, status, suspected cause kèm citations, suspected service, affected services, observations, hypotheses, evidence, missing information, checks, remediation có điều kiện, limitations, input/omitted event IDs, validation status/warnings, thời gian, token usage và estimated cost. Evidence chứa event ID, service, quan sát dạng cấu trúc và nội dung claim mà provider cho rằng được hỗ trợ. Mock trả token usage và cost là null. Provider thật ghi token usage theo SDK. Chưa cấu hình bảng giá có nguồn nên estimated_cost là null.

## Chạy bằng PowerShell

Từ thesis-log-anomaly với Context stack đang healthy:

```powershell
$env:LLM_PROVIDER = 'mock'
$env:LLM_ALLOW_EXTERNAL = '0'
docker compose --env-file .env.elk --env-file .env.context --env-file .env.detection -f compose.yaml -f compose.logging.yaml -f compose.context.yaml -f compose.detection.yaml -f compose.llm.yaml up -d --build --no-deps llm-service
Invoke-RestMethod http://127.0.0.1:8016/ready
$body = @{trace_id='09b71700f5dca84ec31f133b92b2ba91'; mode='cross_service'} | ConvertTo-Json
$result = Invoke-RestMethod http://127.0.0.1:8016/analyze/trace -Method Post -ContentType application/json -Body $body
Invoke-RestMethod "http://127.0.0.1:8016/analysis/$($result.analysis_id)"
```

Để thực hiện một lượt OpenAI trên log lab đã được phép gửi, cấp `OPENAI_API_KEY` vào environment theo cơ chế quản lý secret của máy, đặt `LLM_PROVIDER=openai`, `LLM_MODEL` bằng model ID hỗ trợ Structured Outputs, `LLM_ALLOW_EXTERNAL=1`, `LLM_CALL_CAP=1` và recreate riêng llm-service. Ghi snapshot model cụ thể khi nghiên cứu. Chế độ mặc định thiếu key/model hoặc chưa bật cờ sẽ trả 503. Tránh hiển thị Compose config có giá trị nội suy.
