# Mốc thời gian collector 7A.5E

Dùng monotonic clock. T0 là thời điểm bắt đầu collector.

| Mốc | Giới hạn |
|---|---|
| Preflight | T0 + 120 giây |
| Activation, lookup fixture và readiness | T0 + 300 giây |
| Một POST | Tối đa 12 giây, cắt ở T0 + 300 |
| Capture và seal/receipt | Tối đa 120 giây sau khi nhận response |
| Cleanup và postflight | Tối đa 30 giây kể từ khi bắt đầu cleanup, chạy ngay sau capture kể cả khi lỗi |
| Snapshot | Chờ đến 420 giây sau response, thêm tối đa 30 giây cho truy xuất/validation |
| Overall safety envelope | T0 + 792 giây, gồm các phần dự trù bảo thủ |

Giữ cutoff 420 giây tương đối theo response rồi lấy hai snapshot và đối chiếu receipt đã lưu. Không giữ fault bật trong thời gian chờ. Snapshot là đối chiếu gần cutoff trong cửa sổ 30 giây, không suy ra thời điểm index chính xác của từng event. Nếu tập event đổi, bước reconcile dừng. HTTP client có timeout theo thao tác và subprocess chịu deadline còn lại; đây là giới hạn điều phối trong điều kiện tiến trình đáp ứng timeout, không phải watchdog cho tình trạng host treo.

Timeout lưu artifact đã ghi kèm attempt, HTTP response hoặc capture từng phần nếu đã có. Bất nhất trả INCOMPLETE. Cleanup dùng cửa sổ riêng và ghi lỗi thay vì retry POST. Fake clock test chạy qua mốc snapshot, nhánh timeout và budget request mà không chờ 420 giây thật.
