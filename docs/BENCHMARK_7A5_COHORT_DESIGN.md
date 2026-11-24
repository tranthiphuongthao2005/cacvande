# Thiết kế cohort 7A.5A

Mục tiêu tối đa 28 trace mới từ 7 nhóm, 2 cấu hình mỗi nhóm và 2 lần thực thi mỗi cấu hình. Sáu cấu hình có đường chạy trong lab nhưng chưa xác minh tính độc lập. Tám slot DESIGN_BLOCKED. Nếu chỉ xét sáu cấu hình có đường chạy, trần lý thuyết là 12 trace trước các gate và trước khi gộp nhóm phụ thuộc.

| Nhóm | A · đường chạy hiện có | B · yêu cầu thiết kế tiếp |
|---|---|---|
| Normal | Order → User/Product → lưu Order, HTTP 201 | Luồng Order khỏe có đường dependency khác thực chất |
| Timeout | Product chậm hơn deadline Order, caller 504 | Trì hoãn phản hồi của User trên cạnh Order → User, đo deadline và span |
| Service Unavailable | Product trực tiếp 503, thiếu Order nên bị chặn | Unavailability quan sát từ Order, cần tách cơ chế khỏi Cascade |
| Database Failure | DSN theo request của Order lỗi, PostgreSQL vẫn khỏe | Xác thực DB thất bại trên server truy cập được, có SQLSTATE |
| Processing Failure | Fault hook Order trước INSERT | Vị trí lỗi khác sau validation, có bằng chứng không commit |
| Retry Exhaustion | Product 503 kéo dài qua 3 attempt | Lỗi transport kéo dài qua retry budget, có bằng chứng từng attempt |
| Cascade | Product 503 lan lên Order 502 | Lỗi phát sinh ở User và lan theo cạnh khác |

Tệp cohort_plan.json ghi workload, tham số, evidence, rollback và confounders từng slot. Giá trị TBD là thông tin chặn collection. Không thay seed, timestamp, ID hoặc payload đơn thuần để tạo cấu hình độc lập. Retry, Cascade và Product Unavailable có thể chia sẻ cơ chế Product 503. Phân tầng theo mục tiêu vận hành và gộp cụm phụ thuộc khi phân tích.

Kiểm tra độc lập thực thi bằng run/trace/event ID, khoảng chạy, trạng thái sạch giữa lần chạy và provenance. Kiểm tra cấu hình bằng topology, vị trí lỗi, cơ chế, timeout/retry budget và workload path; so exact signatures và near-duplicates của template, fault hook, fixture, campaign và image. Không để trace, raw event, nhóm hoặc campaign giao nhau qua split. Curator ghi lý do nếu gộp nhóm. Known-fault trên execution mới và known-fault trên cấu hình mới là hai estimand khác nhau. Các cơ chế đã có trong development không đủ điều kiện unseen-fault.

Lịch sử, pilot development, smoke và Batch 01–03 giữ phạm vi cũ. Chỉ run mới chưa phơi bày có thể thành ứng viên. Xem cohort_plan.json để kiểm tra từng slot.
