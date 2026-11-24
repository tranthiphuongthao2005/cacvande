# Tổng hợp benchmark 7A.4

| Batch | Run ID | Cơ chế trong lab | Evidence phân biệt | HTTP Order | Producer / Docker / ES | Cặp |
|---|---|---|---|---:|---:|---|
| 01 | 1d3140d225414983ac361d14ed978220 | Product unavailable, caller Order lan lỗi | Product 503 và Order ghi dependency failure | 502 | 5 / 5 / 5 | Order 3, Cross 5 |
| 02 | 2ffef988d50840d5b59495263fd42c7d | Product delay vượt deadline Order | Caller ghi dependency_timeout; Product hoàn tất 200 sau Order | 504 | 5 / 5 / 5 | Order 3, Cross 5 |
| 03 | a3d1d1c17b614690a9154d7931161e8f | Order không kết nối được qua request DSN | User/Product 200; Order database_connection_failed trước INSERT | 503 | 4 / 4 / 4 | Order 2, Cross 4 |

Ba run TECHNICALLY_VALID, ba cơ chế được quan sát, ba cặp xác minh đúng nội dung Order trong Cross. Mọi Single UNKNOWN, mọi Cross PARTIAL và handoff UNCONFIRMED. Cả ba reviewer status là NEEDS_REVIEW, 0 VERIFIED. HTTP status khác nhau chỉ là biểu hiện; phân biệt cơ chế dựa vào cấu hình chạy và evidence của dependency hoặc repository.

Inventory có 43 trace phân theo cohort: 34 run trong audit 7A (13 engineering history, 7 development, 14 pilot 3B), 4 pilot 7A.1, 2 smoke kỹ thuật và 3 bản ghi audit ứng viên. Các cột thiếu trong nguồn cũ để trống. Ba ứng viên đều EXCLUDED, không có blind evaluation. [Inventory CSV](../experiments/benchmark_7a4_consolidated_inventory.csv)

## Độc lập và độ phủ

Ba HTTP execution có trace ID riêng. Ba campaign cùng triển khai lab, cùng workflow serial Order lookup và dùng lại fixture. Chưa xác minh configuration independence. Cascade và Timeout cùng tập template (Jaccard 1,0) nhưng khác evidence HTTP/dependency; Database có Jaccard 0,5 so với mỗi batch kia và lỗi tại Order thay vì Product. Cả ba trùng chữ ký với lịch sử, không đủ để cắt thành blind groups. Có thể dùng cho development và hướng dẫn reviewer. Known-fault evaluation cần campaign và cấu hình mới đủ phân biệt. Unseen-fault evaluation cần nhóm cơ chế chưa có trong development và phải khóa mục tiêu riêng.

Các variant chưa có trong ba batch 7A.4 là Normal, Service unavailable trực tiếp, Processing failure và Retry exhaustion. Các variant này đã xuất hiện trong dữ liệu lab lịch sử; không tự động tính là cơ chế chưa thấy. Unavailable trực tiếp, Retry và Cascade hiện chia sẻ Product unavailable. Unavailable trực tiếp không có Order nên nằm ngoài phân tích paired chính nếu giữ quy tắc Single Order.

## Reviewer

Hàng đợi 7 hồ sơ gồm 3 P1 batch và 4 P2 pilot. Validator đối chiếu hash dossier với form trống và không tạo quyết định. Người vận hành cấp quyền từng run cho reviewer độc lập; reviewer dùng workflow chữ ký HMAC hiện có và nộp lý do. Thiếu ACK là giới hạn telemetry; không dùng để tự phê duyệt hoặc hủy bằng chứng nguyên nhân đã quan sát. [Reviewer queue CSV](../experiments/benchmark_7a4_reviewer_queue.csv) · [Quy trình import](HUMAN_REVIEW_WORKFLOW.md)
