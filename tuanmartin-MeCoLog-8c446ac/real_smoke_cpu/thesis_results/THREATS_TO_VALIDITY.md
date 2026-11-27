# Các mối đe dọa đối với tính hợp lệ

- **Đơn vị biến động.** Hai mươi seed thay đổi support trên cùng checkpoint và query trong mỗi split. Sample SD và phân vị mô tả độ nhạy với support. Chúng không đo biến động giữa hệ thống, checkpoint hoặc tập query độc lập. Báo cáo dùng thống kê mô tả và delta theo cặp. Chưa thực hiện kiểm định ý nghĩa thống kê hoặc ước lượng khoảng tin cậy tổng quát hóa.
- **Tỷ lệ lớp.** Query có chủ đích gồm 100 Normal và 100 Anomaly. Precision và AP chịu ảnh hưởng của prevalence. FPR final 34,15% của Multi-Prototype là chi phí báo động giả tại ngưỡng 0. Chưa đo trên lưu lượng có prevalence tự nhiên.
- **Hiệu lực nội tại.** Ranh giới 4 event được xác định từ development. Protocol chốt trước final và giữ support IDs, query, checkpoint, threshold giống nhau theo cặp. Không trùng BlockId và raw line ID. Quan hệ qua node, thời gian hoặc sự cố vẫn có thể tồn tại.
- **Hiệu lực cấu trúc.** Độ dài, nội dung và loại sự cố có thể đồng biến. Padding, character OOV và cắt STR/PATH ở C=16 có thể làm thay đổi biểu diễn. Chẩn đoán hiện có chưa cô lập nguyên nhân của tất cả lỗi.
- **Hiệu lực ngoại tại.** Tập con BGL/HDFS, 100 episode, một seed training và một cặp source–target. Thiết lập smoke-scale khác quy mô và cấu hình công bố. Không có cơ sở để tuyên bố đạt benchmark chính thức, vượt bài báo hoặc tổng quát hóa sang hệ thống khác.
- **Recovery.** Lần final đầu đã mở dữ liệu nhưng dừng ở bước ghi JSON. Recovery sử dụng cùng dữ liệu và scorer. Kết quả công bố trong báo cáo là một final đã phục hồi trên cùng tập.
