# Signature overlap và phạm vi đánh giá

Định nghĩa signature là SHA-256 canonical của tập bộ ba service, message, HTTP status trong Cross snapshot. Dữ liệu JSON kết quả liệt kê path/digest từng match. 10/10 trùng acceptance tương ứng và đều có ít nhất một match historical/development ngoài acceptance. Normal trùng pilot/smoke, Processing trùng development pilot, Timeout/Database trùng Batch 02/03 và Cascade trùng pilot/Batch 01.

Execution mới được chứng minh ở mức identity, campaign/repetition, ledger và rollback. Hai execution cùng cấu hình chia sẻ runtime provenance và signature. Điều đó giữ 4 nhóm fault ứng viên, chưa xác minh độc lập thống kê. Mechanism đã xuất hiện trong lịch sử. Snapshot identity riêng và file digest mới. Không dùng khác ID để suy ra cấu hình mới.

HELD_OUT_EXECUTIONS_ON_SEEN_CONFIGURATIONS phù hợp với phép so sánh paired Cross−Single của protocol v2. Tuy vậy đề xuất split 7A.5H yêu cầu giữ họ near-duplicate trong một split và ủy quyền thiết kế hiện có chưa phân xử overlap với development. Formal lock bị chặn với split hiện tại. Bản này giữ EXPLORATORY_COHORT_CANDIDATE, chờ operator và reviewer xác định split hợp lệ. Không tự loại trace, sửa tiêu chí hoặc gọi đây là blind. Phạm vi chỉ là execution mới trong lab trên các cấu hình đã thấy.
