# Quy tắc trace completeness

- **COMPLETE** đòi hỏi ở phạm vi cross-service có chứng cứ đáng tin cậy về root span đã kết thúc, danh sách event mong đợi và các dependency calls được bao phủ, watermark đã đóng, và mọi event tương ứng có trong snapshot không lỗi. `TraceProof` là contract nội bộ thử bằng fixture. Production hiện chưa có nguồn proof kết nối.
- **PARTIAL** khi có dấu hiệu Order POST kết thúc nhưng thiếu proof, hoặc snapshot có lỗi dữ liệu, thiếu span ID, truncation hoặc timeout.
- **UNKNOWN** khi chứng cứ không đủ để xác định kết thúc root, gồm snapshot single-service sạch. Response chỉ mô tả phần quan sát được.

Mỗi lần polling mở PIT mới để nhìn thấy index sau refresh tự nhiên của Elasticsearch. Không ghi hoặc ép refresh từ key chỉ đọc. Cờ `INGESTION_CHANGED_DURING_POLLING` xác nhận hai lần nhìn thấy tập document khác nhau. Snapshot ổn định qua các poll vẫn không đủ chứng minh trace hoàn chỉnh. Thiếu ingest timestamp làm cho phép đo độ trễ end-to-end hiện chưa khả dụng.

Giai đoạn 3B đặt cờ partial bảo thủ trên toàn bộ 14 snapshot dù Docker và Elasticsearch khớp 62 ID. Giai đoạn 4 đọc lại 14 snapshot và khớp đủ ID. Có 12 trace có bằng chứng Order POST kết thúc và hai trace Product độc lập với root chưa xác minh. Dữ liệu đối chiếu không chỉ ra mất event giữa Docker và ES trong tập đó. Không thể loại trừ các event vốn chưa được instrumentation ghi. Log có span ID nhưng thiếu parent ID cùng một watermark đáng tin cậy. Đây là giới hạn chính của completeness hiện tại.

`request_completed` là completion ứng dụng quan sát được. Đối với Order POST có completion, các nhánh User và Product cần xem xét theo luồng gọi, và Product có thể không được gọi sau lỗi User. Caller failure log kèm dependency service chứng minh cạnh báo lỗi. Server completion trong cùng trace chỉ chứng minh sự kiện tại server đó. Thiếu client success/causal span, hệ thống để quan hệ thành công là chưa xác minh.

Duplicate giống hệt được gộp và đếm. Duplicate mâu thuẫn bị cách ly theo ID và đếm. Timestamp trùng được xếp theo ID. Document sai schema, thiếu service hoặc ngoài scope bị bỏ khỏi timeline và có warning/count. Missing span giữ event và tạo warning. Truncation và lỗi ES được báo minh bạch trong response hoặc HTTP có cấu trúc.
