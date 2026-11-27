# Thesis Log Anomaly Lab

[Tiến độ sau merge và kế hoạch tiếp theo](docs/PROJECT_PROGRESS.md)

Giai đoạn 1 gồm ba FastAPI microservice, PostgreSQL riêng cho mỗi service, JSON logs, OpenTelemetry spans và các scenario lỗi có ground truth riêng. Project nằm cạnh thư mục mã nguồn MeCoLog trong workspace.

| Thư mục | Nội dung |
|---|---|
| app/ | API, PostgreSQL repository, telemetry và contract session |
| services/ | Entrypoint và Dockerfile của User, Product, Order |
| experiments/ | Ground truth, runner và dữ liệu quan sát của lab |
| tests/ | Unit, API, Postgres, W3C tracing và fault tests |
| docs/ | Khảo sát MeCoLog và thiết kế tích hợp |
| tools/ | Kiểm tra fingerprint artifact nghiên cứu |

## Chạy stack

Yêu cầu Docker Desktop đang chạy Linux containers và Docker Compose. Từ thư mục này:

```powershell
docker compose config --quiet
docker compose up -d --build
docker compose ps
Invoke-RestMethod http://127.0.0.1:8011/ready
Invoke-RestMethod http://127.0.0.1:8012/ready
Invoke-RestMethod http://127.0.0.1:8013/ready
```

| Service | URL | Resource | Database |
|---|---|---|---|
| User | http://127.0.0.1:8011 | users | users |
| Product | http://127.0.0.1:8012 | products | products |
| Order | http://127.0.0.1:8013 | orders | orders |

Mỗi resource có POST/GET danh sách và GET/PUT/DELETE theo UUID. OpenAPI có tại /docs các service. GET /health đo liveness và GET /ready kiểm tra database. Cấu hình Compose dùng credentials lab và bind API vào loopback.

```powershell
$user = Invoke-RestMethod -Method Post http://127.0.0.1:8011/users -ContentType application/json -Body (@{name='Lab User'; email="lab-$([guid]::NewGuid())@example.com"} | ConvertTo-Json)
$product = Invoke-RestMethod -Method Post http://127.0.0.1:8012/products -ContentType application/json -Body '{"name":"Notebook","price":"12.50"}'
$order = Invoke-WebRequest -UseBasicParsing -Method Post http://127.0.0.1:8013/orders -ContentType application/json -Body (@{user_id=$user.id; product_id=$product.id; quantity=1} | ConvertTo-Json)
$traceId = $order.Headers['x-trace-id']
docker compose logs --no-log-prefix --no-color | Select-String -SimpleMatch $traceId
```

Stop stack bằng docker compose down. Volumes giữ lại dữ liệu khi dùng lệnh này.

## Giai đoạn 2 — Logging tập trung

Overlay tùy chọn thêm Elasticsearch, Kibana và Filebeat. Ba API giữ cổng 8011–8013. Khi overlay bật, app ghi cùng event JSON vào stderr và volume NDJSON để Filebeat thu thập. Truy vấn theo trace_id trong Kibana để nối các service.

- [Khởi động, credentials local, Data View và KQL](docs/ELK_SETUP.md)
- [Schema index, retention và dedup](docs/LOG_SCHEMA.md)
- [Kiểm chứng giai đoạn 2](docs/ELK_VERIFICATION.md)
- [Thiết kế truy xuất DetectionSession](docs/LOG_TO_SESSION_DESIGN.md)

## Fault injection

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m experiments.run_scenario retry
```

Các scenario là normal, timeout, unavailable, database, processing, retry, cascade. Runner chỉ nhắm ba service lab trên loopback, dùng Compose override để đặt tình trạng lỗi qua biến môi trường, sau đó khôi phục Product và Order về cấu hình thường. Trong bài kiểm tra unavailable, Product lookup chủ động trả HTTP 503. Database scenario tạo lỗi kết nối thực bằng DSN không thể kết nối vào cổng loopback của container, trong khi database khởi tạo vẫn tách riêng. Cascade kiểm tra Product 503 dẫn đến Order 502. Telemetry theo trace ID được lưu ở experiments/telemetry/ trước khi container được tái tạo. Kết quả scenario cùng ground truth lưu riêng ở experiments/runs/. Ground truth không nằm trong image service, request, log hay span.

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -m "not integration"
$env:TEST_PG_ADMIN_URL = 'postgresql://lab@127.0.0.1:55439/postgres'
.\.venv\Scripts\python.exe -B -m pytest -q
Remove-Item Env:TEST_PG_ADMIN_URL
```

Dùng PostgreSQL lab riêng và role được phép tạo database. Suite tạo ba database có tên riêng cho lượt test, chạy ba Uvicorn server trên cổng loopback tự chọn, kiểm tra HTTP thật và dọn ba database test sau khi xong. W3C test kiểm tra Trace ID và quan hệ parent span giữa ba service. Suite xác minh retry count và kết quả từng scenario.

## Giai đoạn 3 — Detection API

Detection API chạy trên loopback cổng 8014 và đọc trace thật từ Elasticsearch. Dịch vụ trả `NOT_READY_FOR_SCORING` khi thiếu biểu diễn Microservices đã xác minh và support protocol độc lập. Công cụ ngoại tuyến kiểm tra checkpoint và tensor ứng viên.

- [Kiến trúc API và lệnh chạy](docs/DETECTION_ARCHITECTURE.md)
- [Tích hợp encoder và checkpoint](docs/MECOLOG_INTEGRATION.md)
- [Tiền xử lý và domain shift](docs/MICROSERVICES_PREPROCESSING.md)
- [Thiết kế support protocol](docs/SUPPORT_PROTOCOL.md)
- [Kết quả kiểm chứng](docs/DETECTION_VERIFICATION.md)

## Giai đoạn 3B — Domain compatibility

- [Phân tích domain shift](docs/DOMAIN_SHIFT_ANALYSIS.md)
- [Parser Microservices](docs/MICROSERVICES_PARSER.md)
- [Protocol dataset](docs/MICROSERVICES_DATASET_PROTOCOL.md)
- [Kết quả và điều kiện chấm điểm](docs/SCORING_READINESS.md)

## Giai đoạn 4 — Cross-service Context Retrieval

- [Kiến trúc Context Service](docs/CONTEXT_ARCHITECTURE.md)
- [API và lệnh PowerShell](docs/CONTEXT_API.md)
- [Quy tắc completeness](docs/CONTEXT_COMPLETENESS.md)
- [Kết quả kiểm chứng](docs/CONTEXT_VERIFICATION.md)

## Giai đoạn 5 — Scenario-triggered LLM analysis

- [Kiến trúc LLM Service](docs/LLM_ARCHITECTURE.md) và [API](docs/LLM_API.md)
- [Prompt](docs/LLM_PROMPT_DESIGN.md) và [kiểm tra bằng chứng](docs/LLM_EVIDENCE_VALIDATION.md)
- [Kiểm chứng](docs/LLM_VERIFICATION.md) và [protocol đánh giá](docs/LLM_EVALUATION_PROTOCOL.md)
- [Cấu hình provider thật](docs/REAL_LLM_SETUP.md) và [kiểm chứng giai đoạn 5B](docs/REAL_LLM_VERIFICATION.md)

## Giai đoạn 6 — n8n orchestration

- [Kiến trúc](docs/N8N_ARCHITECTURE.md), [thiết lập](docs/N8N_SETUP.md), [workflow](docs/N8N_WORKFLOW.md) và [kiểm chứng](docs/N8N_VERIFICATION.md)

## Giai đoạn 7A — Chuẩn bị benchmark độc lập

- [Thiết kế benchmark](docs/BENCHMARK_DESIGN.md), [ground truth](docs/GROUND_TRUTH_PROTOCOL.md) và [rubric chấm](docs/LLM_EVALUATION_RUBRIC.md)
- [So sánh theo cặp](docs/PAIRED_EVALUATION.md) và [readiness](docs/BENCHMARK_READINESS.md)

## Giai đoạn 7A.1 — Pilot thu thập có kiểm soát

- [Collector](docs/BENCHMARK_COLLECTION.md), [độc lập và tách tập](docs/BENCHMARK_INDEPENDENCE.md), [chất lượng dữ liệu](docs/BENCHMARK_QUALITY_REPORT.md) và [readiness](docs/BENCHMARK_7A1_READINESS.md)

## Giai đoạn 7A.2 — Xác minh nhãn và completeness

- [Hồ sơ ground truth](docs/GROUND_TRUTH_VERIFICATION.md), [protocol telemetry](docs/TELEMETRY_COMPLETENESS_PROTOCOL.md), [watermark](docs/WATERMARK_DESIGN.md) và [readiness](docs/BENCHMARK_7A2_READINESS.md)

## Giai đoạn 7A.3 — Receipt thật và nhập phiếu reviewer

- [Receipt](docs/REAL_TELEMETRY_RECEIPTS.md), [Context v2](docs/COMPLETENESS_INTEGRATION.md), [reviewer workflow](docs/HUMAN_REVIEW_WORKFLOW.md) và [readiness](docs/BENCHMARK_7A3_READINESS.md)

## Giai đoạn 7A.3B — Producer event accounting

- [Accounting](docs/PRODUCER_EVENT_ACCOUNTING.md), [phạm vi completeness](docs/BOUNDED_COMPLETENESS.md), [kiểm chứng](docs/BENCHMARK_7A3B_VERIFICATION.md) và [readiness](docs/BENCHMARK_7A3B_READINESS.md)

## Giai đoạn 7A.4 — Mở rộng có kiểm soát

- [Kế hoạch campaign](docs/BENCHMARK_7A4_COLLECTION_PLAN.md), [chất lượng](docs/BENCHMARK_7A4_QUALITY_REPORT.md), [độc lập](docs/BENCHMARK_7A4_INDEPENDENCE.md) và [readiness](docs/BENCHMARK_7A4_READINESS.md)

## Tài liệu tham chiếu

- [Kiến trúc, giới hạn và hợp đồng session](docs/ARCHITECTURE.md)
- [Khảo sát nguồn MeCoLog và dependency cho Detection API](docs/MECOLOG_HANDOFF.md)
- [Ground truth lab](experiments/ground_truth.json)
- [Kết quả kiểm chứng giai đoạn 1](docs/VERIFICATION.md)

Chạy .\.venv\Scripts\python.exe -B .\tools\audit_research.py để kiểm tra checksum nguồn nghiên cứu. MeCoLog inference, Context Retrieval, LLM và n8n thuộc các giai đoạn sau.
