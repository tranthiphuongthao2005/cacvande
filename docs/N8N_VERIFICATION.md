# Kiểm chứng n8n

Docker dùng image n8n 2.48.7 với digest `sha256:fabce3e9678a07d2dde83bd8f5124017f3ec457d0a3fc6b63bb4cec465d63861`. CLI import thành công một workflow và chấp nhận publish `thesisScenario01`. Chạy CLI với server đã dừng để tránh hai process Node dùng chung giới hạn RAM. Cold-start n8n kéo dài do tải image và migration lần đầu. Ba database ứng dụng giữ nguyên volume.

Pytest **49/49** trong 51,37 giây với ba cảnh báo deprecation có sẵn. Các bài mới kiểm tra Bearer, schema, ground-truth isolation, idempotency, persistence, phân loại provider/context/timeout, guard mock trước khi generation và cooldown local notification. Regression database dùng PostgreSQL lab riêng.

## Production webhook

POST `http://127.0.0.1:5678/webhook/scenario-incident` đã chạy nhánh trả kết quả trên trace `09b71700f5dca84ec31f133b92b2ba91`. Lượt cross-service giữ 5 event và lưu incident `61e6be38fb86438a8f61525fa61c43f0` với model mock `mock-rca-v1`, completeness `PARTIAL`, status `INSUFFICIENT_EVIDENCE`, cờ review và latency adapter 2.167,389 ms. Report reference là `incident-store:61e6be38fb86438a8f61525fa61c43f0`.

| Kiểm tra | Kết quả |
|---|---|
| Thiếu hoặc sai Bearer | 401 |
| Chèn field ground truth | 422, giá trị input không bị echo |
| Đổi scope với cùng key | 409 |
| Lặp lại cùng key/scope | Cùng incident ID và `replayed=true` |
| Downstream mới | 1 lần gọi LLM mock, 1 lần gọi Context trực tiếp từ adapter và 1 lần Context bên trong LLM |
| Incident / notification | 1 incident, 0 notification |
| Detection / audit | HTTP 503 `NOT_READY_FOR_SCORING`, 63 fingerprint khớp |

Sau khi recreate n8n và restart adapter với cùng volumes, đăng nhập owner vẫn thành công. Replay báo cùng incident ID, với 0 lượt gọi Context và LLM mới. Đọc SQLite chỉ đọc xác nhận đúng 1 claim, 1 báo cáo đã lưu và 0 notification. [Artifact persistence](../experiments/n8n_persistence_verification.json)

Tại lần đo sau replay, n8n dùng 526,6 MiB trên 640 MiB và CPU 1,57%; incident-adapter dùng 39,03 MiB trên 128 MiB và CPU 0,20%. Cả hai container đều healthy. Giới hạn grant TTL runner được tăng lên 180 giây sau khi log startup ghi nhận TTL mặc định hết hạn trên Docker Desktop. Workflow dùng node tích hợp sẵn và không dùng Python runner.

Lần thử HTTP đầu đến ngay sau readiness và trước lúc webhook được đăng ký; sau khi registration hoàn tất, verifier qua đủ bước. Setup owner ban đầu đã commit nhưng HTTP response timeout trước khi credential được lưu. Đã khôi phục duy nhất mật khẩu owner lab được tạo trong lần triển khai này và kiểm chứng đăng nhập. Helper hiện lưu credential local trước POST và xác minh bằng login, giúp xử lý timeout mà không phải tạo owner khác. [Artifact webhook](../experiments/n8n_verification.json)

## File triển khai

- `compose.n8n.yaml`, `services/incident/Dockerfile`, `workflows/scenario-incident.json`.
- `app/incident_workflow.py`, guard header trong `app/llm_api.py`.
- `tools/init_n8n_env.py`, `tools/init_n8n_owner.py`, `tools/verify_n8n.py`, `tests/test_incident_workflow.py`.
- README, .gitignore và bốn tài liệu n8n.

## Giới hạn

ELK Context đọc snapshot đã có. Filebeat health probe timeout trong lúc tải image và trở lại healthy ở lần kiểm tra cuối. Giai đoạn này không sửa ELK hoặc xác nhận ingestion mới. n8n và adapter đều chạy single-instance. TTL ledger là dọn khi có lần claim tiếp theo. Pending không tự retry, tránh gửi lại khi chưa biết trạng thái của lượt trước. LLM guard chỉ cho mock qua workflow. Không gửi notification ra ngoài, không thực thi remediation và không publish detection-triggered workflow.

Lệnh PowerShell nằm trong [hướng dẫn thiết lập](N8N_SETUP.md).
