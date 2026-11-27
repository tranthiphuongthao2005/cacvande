# Cấu hình OpenAI provider

`.env.example` liệt kê cấu hình không chứa khóa. Cấp `OPENAI_API_KEY` qua trình quản lý secret vào environment của phiên PowerShell hiện tại. Không đưa khóa lên dòng lệnh, vào file báo cáo hoặc vào log. `.env.llm` có thể lưu phần cấu hình không nhạy cảm và đã được ignore; verifier cần model và cờ cho phép trong chính process environment. Không in Compose config nội suy.

Với trace lab đã được xác minh và chi phí đã được người vận hành chấp thuận, đặt model snapshot hỗ trợ Structured Outputs vào `LLM_MODEL`. Giá trị bên dưới là chỗ điền, không phải model ID đã xác minh quyền truy cập. Dùng cùng phiên shell cho Compose và verifier, không gửi request song song tới instance này.

```powershell
$env:LLM_PROVIDER = 'openai'
$env:LLM_MODEL = '<approved-model-snapshot>'
$env:LLM_ALLOW_EXTERNAL = '1'
$env:LLM_CALL_CAP = '2'
$env:LLM_VALIDATION_RETRIES = '0'
$env:LLM_INPUT_BUDGET = '7000'
docker compose --env-file .env.elk --env-file .env.context --env-file .env.detection -f compose.yaml -f compose.logging.yaml -f compose.context.yaml -f compose.detection.yaml -f compose.llm.yaml up -d --build --no-deps llm-service
Invoke-RestMethod http://127.0.0.1:8016/ready
$stamp = Get-Date -Format yyyyMMdd_HHmmss
.\.venv\Scripts\python.exe -B -m tools.verify_real_llm --approve-api-cost --output ".\experiments\llm_real_$stamp.jsonl"
```

Nếu trace mặc định đã hết retention, truyền `--trace-id` của cascade mới kiểm chứng. Verifier kiểm tra pattern User 200, Product 503, Order 502 và log Order báo lỗi gọi Product trong cùng trace. Nó yêu cầu hai suất gọi còn nguyên, retry validation bằng 0 và cùng model/prompt/config. Một lần gửi Single và một lần gửi Cross. Dừng sớm khi một bước lỗi hoặc scope không còn khớp. Timeout phía client không xác định chắc request đã đến provider hay chưa; kiểm tra log metadata trước khi cân nhắc một lượt khác. Bộ đếm nằm trong process, nên restart tạo ngân sách mới.

GET /health đo process, GET /ready kiểm cấu hình cục bộ và ngân sách còn. Readiness không xác thực khóa với OpenAI. Provider gửi evidence đã chiếu qua allowlist bằng SDK chính thức, Responses API với `store=False`, timeout 20 giây, retry SDK 0, max output 1.200 và decoding mặc định của cùng model. [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

Verifier ghi JSONL metadata từng lượt, bỏ nội dung tự do và không ghi khóa. Dùng GET /analysis/{analysis_id} để rà soát báo cáo còn trong RAM. Kiểm tra riêng việc phân biệt symptom với nguyên nhân và quan hệ dependency. Câu chữ chưa có bằng chứng phải được đánh dấu cần review, giữ nguyên kết luận gốc. Chưa cấu hình bảng giá nên estimated_cost là null.
