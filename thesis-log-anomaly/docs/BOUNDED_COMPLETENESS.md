# Completeness có giới hạn

Đơn vị kiểm tra là run ID, trace ID W3C, tập ba service User/Product/Order và accounting version `producer-accounting-v1`. Khoảng thu là từ event đầu tiên của scope đến từng mốc `closed_at` của seal. Local boundary Order SERVER có parent là span CLIENT điều khiển smoke, nằm ngoài ba producer. Không diễn giải local boundary là toàn hệ thống phân tán.

Điều kiện cần gồm request trong phạm vi đã kết thúc, đồ thị span khép kín trong boundary, producer ledger không gaps hay emission lỗi, tất cả seal hợp lệ, không event sau seal trong kỳ quan sát, tập ID/nội dung Docker/ES khớp ledger, handoff có xác nhận và scope producer đầy đủ có nguồn đáng tin. Một kết quả ingestion match không chứng minh từng lần chuyển qua Filebeat đều thành công. Còn thiếu ACK và kiểm kê toàn producer ngoài logger đã instrument, nên bundle thực nghiệm có `OBSERVED_CAPTURE_ONLY`. Không có COMPLETE.

Context v1 giữ schema và kết quả. V2 giữ các field đã có, thêm accounting version, digest evidence, service set và cờ handoff trong provenance khi bundle có accounting. API so lại hash từng event hiện tại. Cross không nâng khỏi PARTIAL khi thiếu bằng chứng. Single giữ UNKNOWN theo scope, không đánh đồng nội dung của Order với toàn trace. Receipt 7A.3 cũ tiếp tục đọc được từ mount cũ. Snapshot lịch sử không được làm mới hoặc ghi đè.
