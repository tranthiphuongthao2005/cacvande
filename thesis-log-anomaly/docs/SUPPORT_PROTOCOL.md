# Thiết kế protocol support Microservices

Trạng thái hiện tại là `NOT_READY_FOR_SCORING`. Bảy trace từ kiểm chứng ELK dùng cho adapter và tiền xử lý. Chúng không đủ để khóa ba pool độc lập hoặc bao phủ lỗi đa dạng. Không tái dùng prototype HDFS và không lấy nhãn query từ kịch bản để tạo prototype.

| Pool | Vai trò |
|---|---|
| Support | Trace gán nhãn từ hồ sơ fault độc lập hoặc chuyên gia, có thời điểm, người gán, nguồn và căn cứ |
| Development | Kiểm tra readiness, domain shift, độ dài, FPR và chọn ràng buộc trước khi khóa |
| Evaluation | Một tập trace đã khóa dùng sau khi các quyết định hoàn tất |

Nhóm trace theo scenario family, topology, cấu hình tạo lỗi và signature gần trùng sau khi loại các ID ngẫu nhiên. Giữ toàn bộ nhóm trong cùng một split và thu nhiều nhóm độc lập cho cả Normal và Anomaly. Cùng trace ID hoặc event ID bị từ chối. `validate_pools` kiểm tra ID và group đã khai báo; việc kiểm tra gần trùng và phê duyệt căn cứ nhãn là bước ngoại tuyến của protocol. Khóa tập ID, group, nhãn support, code/config, fingerprint feature, checkpoint, seed, thứ tự support, scoring method và threshold trước đánh giá. Dùng query cố định khi so sánh hai phương pháp. Chỉ phát hành protocol ID khi chứng minh được tách nhóm và truy xuất được provenance.

Single-Prototype chuẩn hóa L2 từng embedding support, lấy centroid theo lớp rồi chuẩn hóa lại. Điểm bằng cosine Anomaly trừ cosine Normal. Length-Aware Multi-Prototype giữ Normal centroid và chia Anomaly support theo true length ≤4 và >4, mỗi nhóm cần ít nhất hai support. Khi thiếu, dùng chung Anomaly centroid. Query chỉ đóng góp embedding; điểm dùng max cosine Anomaly rồi trừ cosine Normal. Dự đoán anomaly khi score >0. Ranh giới 4 xuất phát từ HDFS development. Hiệu lực trên Microservices cần đánh giá riêng. API kiểm tra support/query overlap trước khi đưa query vào đường chấm điểm đã duyệt.
