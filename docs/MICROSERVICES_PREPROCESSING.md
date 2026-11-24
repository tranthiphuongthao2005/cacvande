# Tiền xử lý log Microservices

BGL cắt cửa sổ trên thứ tự dòng gốc. HDFS gom theo BlockId. Microservices gom span/log theo trace ID, có fan-out, retry, ingestion lag và nhiều service. Cả ba tạo đơn vị quan sát khác nhau, nên cùng tensor shape không thiết lập tính tương đương.

Ứng viên chẩn đoán chuyển mỗi structured event thành chuỗi `service event_name level` và nối `status=<http_status>` khi có HTTP status. Chỉ các service và event thuộc allowlist được nhận. Cách chiếu này không dùng message tự do, timestamp, UUID, request body, trace ID hay nhãn kịch bản làm feature. Nhược điểm là bỏ các tín hiệu nghiệp vụ ngoài allowlist, gồm route, duration và mã lỗi chi tiết. Không có chuỗi raw Content chuẩn tương đương benchmark, vì vậy đây là biểu diễn ứng viên cần được duyệt và đánh giá riêng.

Adapter tái dựng Drain gốc trên 204 HDFS training session cũ, chỉ lấy raw line ID training. Nó đối chiếu 3.962 dòng theo template/EventId. Không mở CSV nhãn HDFS hoặc các feature final. TreeSearch đóng băng ở depth 4, threshold 0,5. Event chưa match dùng template của token đã mask theo nhánh fallback gốc, đồng thời tăng bộ đếm unseen. Frozen vocabulary lấy từ BGL training, PAD=0, UNK=1. Loại tham số lần lượt là NUM=0, IP=1, HEX=2, PATH=3, STR=4. Parameter encoder gốc giữ signed log1p cho NUM, mã ký tự cho STR/PATH và chuẩn hóa PATH.

Tensor đầu vào gồm `x:[B,50,768]`, `p_key:[B,50,8]`, `p_type:[B,50,8]`, `p_num:[B,50,8]`, `p_val:[B,50,8,16]`. `x,p_num` là float32, ba tensor ID là int64. Dùng tối đa 50 event đầu và zero-padding bên phải. Không có tensor nhãn. P=8, C=16. Zero slot dùng type ID 0 theo schema gốc. Encoder gốc không có padding mask; chênh lệch độ dài 1–9 event cần được đánh giá riêng.

Trên 31 event thật, có 31 fallback, 0 event bị cắt và 319 vị trí padding trên 350. Tất cả 29 key được mã hóa là OOV. Character OOV có mẫu số 0 vì các slot thực tế chỉ chứa tham số số. Không có bằng chứng biểu diễn này mang đủ tín hiệu để suy diễn anomaly. Checkpoint đã strict-load nhưng tensor ứng viên không đi qua MeCoLog.
