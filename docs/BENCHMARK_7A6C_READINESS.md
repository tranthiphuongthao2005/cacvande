# Readiness 7A.6C

Năm cấu hình có đường tới shared gated collector. Timeout A, Database A và Cascade A là đường triển khai mới, đã qua kiểm offline, chờ live acceptance. Normal A và Processing A có historical live evidence từ lượt trước. Không thêm B hoặc Retry. Không có POST nghiệp vụ, fault live hoặc OpenAI calls. Collection BLOCKED. Còn 0 independent VERIFIED, 0 ground truth VERIFIED và 0 blind eligible.

Điều kiện trước acceptance là phê duyệt operator theo từng lượt, readiness host, image/cấu hình hiện hành đúng hook, scope và output độc quyền, và hậu kiểm rollback/telemetry. Nếu marker runtime tồn tại, cần operator điều tra và xác minh recovery. Handoff UNCONFIRMED vẫn là giới hạn completeness. Không mở benchmark.

Docker Engine đọc được khi được cấp quyền. User/Product/Order đang Up; Context, Elasticsearch, Filebeat và ba PostgreSQL container báo healthy; Kibana unhealthy. GET /ready từ host tại 8011/8012/8013/8015 đều timeout, kể cả bỏ qua proxy. Readiness end-to-end chưa xác minh và phải qua preflight trước acceptance. Không recreate hay thay runtime.
