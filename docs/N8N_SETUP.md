# Thiết lập n8n local

Chạy trong `thesis-log-anomaly` với stack giai đoạn 5 đã có. n8n dùng user-management owner cho editor và yêu cầu Bearer riêng cho webhook scenario. HTTP localhost cần `N8N_SECURE_COOKIE=false`; chỉ bind 127.0.0.1. Không dùng cấu hình này qua LAN. Lưu tài khoản owner trong trình quản lý mật khẩu. Chỉ đọc secret trigger vào bộ nhớ khi gọi webhook.

```powershell
if (-not (Test-Path .env.n8n)) { .\.venv\Scripts\python.exe -B -m tools.init_n8n_env }
$env:LLM_PROVIDER = 'mock'
$env:LLM_ALLOW_EXTERNAL = '0'
$stack = @('--env-file','.env.elk','--env-file','.env.context','--env-file','.env.detection','--env-file','.env.n8n','-f','compose.yaml','-f','compose.logging.yaml','-f','compose.context.yaml','-f','compose.detection.yaml','-f','compose.llm.yaml','-f','compose.n8n.yaml')
docker compose @stack up -d --build --no-deps n8n incident-adapter llm-service
docker compose @stack exec -T n8n n8n --version
```

Để tránh chạy hai process Node trong giới hạn RAM của container, dừng riêng n8n trước khi import và publish bằng container CLI dùng cùng volume. Tạo owner qua UI tại http://127.0.0.1:5678 khi mở lần đầu, hoặc dùng `tools.init_n8n_owner` để tạo credential ngẫu nhiên vào file local đã ignore.

```powershell
docker compose @stack stop -t 20 n8n
docker compose @stack run --rm --no-deps -T n8n import:workflow --input=/workflows/scenario-incident.json
docker compose @stack run --rm --no-deps -T n8n publish:workflow --id=thesisScenario01
docker compose @stack up -d --no-deps --no-build n8n
.\.venv\Scripts\python.exe -B -m tools.init_n8n_owner
$stamp = Get-Date -Format yyyyMMdd_HHmmss
.\.venv\Scripts\python.exe -B -m tools.verify_n8n --output ".\experiments\n8n_verification_$stamp.json"
```

Import/publish một lần cho workflow version này. Chờ healthcheck sau khi khởi động; cold-start đầu chạy migration. Dùng `--trace-id` nếu cascade mẫu hết retention. Không xóa volume PostgreSQL hoặc volume của n8n. [CLI publish n8n](https://docs.n8n.io/deploy/host-n8n/configure-n8n/use-the-command-line.md)
