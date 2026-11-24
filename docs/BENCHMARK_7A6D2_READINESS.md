# Readiness 7A.6D.2

Docker Engine 29.2.1. User, Product, Order Up. Context, ES, Filebeat và ba PostgreSQL healthy. GET /ready từ host trả HTTP 200 ở User 1,008 s, Product 0,875 s, Order 0,333 s, Context 1,232 s với timeout 4 giây. Tất cả fault flags và accounting scopes được kiểm tra đều trống. Không có collection_runtime_lock hoặc approval-usage ledger lúc kiểm. Kibana unhealthy, tách khỏi đường collector. Đây là probe chuẩn bị, cần lặp preflight ngay trước mỗi batch thực tế.

Normal A PASS sau approval riêng. Preflight và postflight đều ghi bốn HTTP 200, fault/scope baseline sau rollback và không marker. Approval một lần đã được ghi ledger. Các adapter khác nằm ngoài phạm vi. Biến động fixture Processing vẫn INTERMITTENT_UNRESOLVED.

Sau khi operator duyệt bốn adapter còn lại, cả bốn gate offline đạt nhưng chuỗi dừng ngay preflight Processing A do User 8011/ready timeout 4,007 giây. Hậu kiểm chỉ đọc ghi User 200/0,550 s, Product timeout 4,008 s, Order 200/3,784 s, Context 200/1,703 s. ES, Filebeat, ba PostgreSQL và Kibana báo healthy tại hậu kiểm. Fault flags/scopes trống và runtime marker không tồn tại. Khả năng readiness trong 4 giây vẫn chưa ổn định. Dừng chuỗi, không retry hoặc activation.

Sau ổn định runtime, đạt 40/40 readiness, và bốn adapter còn lại PASS tuần tự. Sáu container phụ trợ/demo đã khởi động lại. Hậu kiểm sau khôi phục đạt bốn HTTP 200 trong 0,512–2,124 giây; ES, Filebeat và ba DB healthy; n8n và Kibana đang health starting lúc quan sát. Fault flags/scopes trống, không runtime marker. Trước 7A.7 cần approval collection riêng, xác minh độc lập và split, reviewer và chính sách completeness. 0 independent VERIFIED, 0 ground truth VERIFIED và 0 blind-eligible.

Điều kiện chuyển sang 7A.7 gồm hoàn tất acceptance đã được duyệt, hậu kiểm runtime và integrity, operator duyệt kế hoạch blind cohort và tách split/campaign, xác minh độc lập cấu hình và governance riêng để thu. Không đưa acceptance vào blind set. Hiện 0 independently verified, 0 ground truth VERIFIED và 0 blind-eligible. Việc nghiệm thu adapter không tự mở quyền collection blind hoặc khóa benchmark.
