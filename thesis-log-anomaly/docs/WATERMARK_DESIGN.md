# Thiết kế watermark

Thay đổi nhỏ nhất là giữ marker request_completed, span exporter và schema Context hiện có, rồi bổ sung nguồn proof riêng cho các lượt thu tương lai. Nguồn này độc lập với payload labels và với snapshot ES đang kiểm tra.

1. Collector theo dõi event ID và span ID từ nguồn cho từng trace. Khi root và các dependency dự kiến khép lại, đóng capture có timestamp cutoff và danh sách ID đã khóa. Đánh dấu nguồn không đủ nếu exporter drop, có child không kết thúc hoặc chỉ biết tập ID từ ES.
2. Trong một index/pipeline revision tương lai, ghi ingest timestamp mới từ ES cho log mới, giữ event timestamp cũ. Ingest timestamp phản ánh ES xử lý document, cần kết hợp với việc đọc được ID sau refresh để xác nhận delivery trong phạm vi thu thập. Pilot không có field đó hoặc Filebeat delivery ACK theo event.
3. Collector dùng bounded polling qua PIT mới lấy snapshot sau cutoff, đối chiếu expected event IDs và ingest/visibility timestamps. Chờ đến timeout thì trả trạng thái chưa settled. Một giai đoạn im lặng hoặc hai lần query có cùng số event không thể thay thế source seal. Event đến muộn ngoài tập đã khóa là dấu hiệu audit lại capture.
4. Trước khi nối Context với proof, thêm trust boundary xác minh nguồn receipt, khóa trace và các checksum. Chỉ cấp COMPLETE cho snapshot cross-service mới có đủ bằng chứng. Giữ kết quả lịch sử.

**Trạng thái triển khai:** evaluator ngoại tuyến đã kiểm các mốc và graph với fixture. Producer, ingest timestamp, delivery receipt và Context wiring chưa triển khai. Không sửa instrumentation, hệ thống log hay behavior fault trong 7A.2.
