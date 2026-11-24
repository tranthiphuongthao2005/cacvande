# Elastic Stack local

Overlay compose.logging.yaml bổ sung Elasticsearch, Kibana và Filebeat 8.19.25, hai init job và các volume riêng. Base compose giữ ba service, ba PostgreSQL và cổng 8011–8013. Không xóa volume để đổi chế độ.

## Khởi động

Từ thư mục thesis-log-anomaly, tạo credential ngẫu nhiên một lần. Lưu .env.elk ở máy local, ngoài git và build context. Khi file đã có, bỏ qua lệnh tạo.

```powershell
.\.venv\Scripts\python.exe -B .\tools\init_elk_env.py
docker compose --env-file .env.elk -f compose.yaml -f compose.logging.yaml config --quiet
docker compose --env-file .env.elk -f compose.yaml -f compose.logging.yaml up -d --build
docker compose --env-file .env.elk -f compose.yaml -f compose.logging.yaml ps
```

- Elasticsearch tại http://127.0.0.1:9200, Kibana tại http://127.0.0.1:5601. Đăng nhập Kibana bằng elastic và ELASTIC_PASSWORD trong .env.elk. Dùng credential tương tự khi gọi API xác thực của ES. Ví dụ PowerShell có thể dùng curl.exe --user elastic http://127.0.0.1:9200/_cluster/health và nhập mật khẩu khi được hỏi.
- Elastic xác thực và phân quyền đang bật. Overlay development đơn node dùng HTTP ở loopback và mạng logging riêng của Compose, chưa bật TLS. Coi host và các container chung mạng là môi trường tin cậy. Không mở bind ra LAN. Kibana dùng kibana_system. Filebeat dùng role writer giới hạn thesis-logs-* và quyền cluster monitor cho kết nối. Bootstrap là job duy nhất dùng credential quản trị để cài role, pipeline và ILM.
- Elasticsearch giới hạn 1.152 MiB, Java heap 384 MiB. Kibana giới hạn 896 MiB, Node heap 512 MiB. Filebeat giới hạn 160 MiB. Cả ba giá trị là giới hạn, không phải số đo tải thực tế. Dữ liệu ES và registry Filebeat có volume bền.
- Filebeat không dùng Docker socket. App ghi bản JSON đồng nhất vào stderr và NDJSON. Mỗi app chỉ gắn volume log của mình; Filebeat đọc ba volume ở chế độ ro, chạy UID 10001 với mọi capability bị loại. Init permissions chỉ chạy trên volume log và registry, không truy cập volume DB.

## Chạy scenario và kiểm chứng

```powershell
.\.venv\Scripts\python.exe -B -m experiments.run_scenario cascade --elk
.\.venv\Scripts\python.exe -B .\tools\verify_elk.py --output .\experiments\elk_verification_repeat.json
```

Verifier chạy lại 7 scenario thật, tạo Kibana Data View nếu chưa có và đối chiếu từng event theo event_id. Dùng đường dẫn output mới khi chạy lại. Khi overlay đang bật, truyền --elk để runner duy trì volume và môi trường ghi file.

Overlay dùng ngân sách gọi dependency 2 giây để giảm timeout ngoài dự kiến khi Elastic Stack dùng chung tài nguyên. Fault timeout vẫn trì hoãn Product lâu hơn ngân sách này. Các ngưỡng giai đoạn 1 trong base Compose dùng cấu hình cũ.

## Kibana Discover

Chọn data view **Thesis application logs** (thesis-logs-*, @timestamp). Đặt time range bao phủ thời gian chạy lab, thêm cột service_name, status_code, duration_ms, error_type, dependency_service và sắp xếp @timestamp tăng dần.

| Mục đích | KQL |
|---|---|
| Log riêng Order | service_name: "order" |
| Log lỗi | level: "ERROR" |
| 5xx | status_code >= 500 |
| Cùng trace | trace_id: "<trace-id>" |
| Timeout Product | error_type: "dependency_timeout" and dependency_service: "product" |
| Cascade | trace_id: "<cascade-trace-id>" and service_name: ("user" or "product" or "order") |

Với cascade, kiểm tra User lookup 200, Product lookup 503, Order 502 trong cùng trace. Dùng timestamp cho trình tự quan sát; thứ tự sắp xếp trong Discover không tự chứng minh quan hệ nhân quả.

## Tắt riêng nhóm logging

```powershell
docker compose --env-file .env.elk -f compose.yaml -f compose.logging.yaml stop filebeat kibana elasticsearch
```

Ba app vẫn chạy và ghi các file log có rotation. Khi muốn bỏ cả ghi file, chạy docker compose -f compose.yaml up -d user-service product-service order-service. Thao tác này có thể thay container ứng dụng theo cấu hình base và giữ nguyên PostgreSQL cùng volumes. Nếu cần resume, chạy lại lệnh up của overlay. Không dùng down -v.
