# Tóm tắt kết quả cho khóa luận

Nghiên cứu đánh giá Length-Aware Multi-Prototype trên thiết lập few-shot cross-system BGL → HDFS quy mô nhỏ. Hai phương pháp dùng cùng checkpoint MeCoLog 100 episode huấn luyện trên BGL và cùng support IDs theo seed. Biến thể nghiên cứu chia Anomaly support theo ranh giới bốn event đã xác định trên development. Scorer sử dụng maximum cosine với các Anomaly prototype, giữ Normal prototype và ngưỡng 0.

Trên HDFS final, Binary F1 trung bình tăng từ 0,6473 lên 0,7897, ROC-AUC tăng từ 0,6104 lên 0,9116 và Recall tăng từ 0,4900 lên 0,8675. Binary F1 và ROC-AUC tăng ở 20/20 cặp seed. FPR tăng từ 2,65% lên 34,15%, tương đương **31,50 điểm phần trăm**, và Precision giảm từ 0,9603 xuống 0,7347. Macro F1 tăng trung bình nhưng giảm ở 9/20 seed. Phân tích hậu kiểm cho thấy Recall tăng ở Anomaly dài, rõ nhất với nhóm 20–29 event.

Kết quả hỗ trợ khả năng xếp hạng tốt hơn và phát hiện thêm Anomaly dài trên query đã kiểm tra, với chi phí báo động giả lớn hơn ở ngưỡng cố định. Hai mươi seed chia sẻ checkpoint và query pool cân bằng. Dữ liệu hiện có chưa xác lập hiệu năng với prevalence tự nhiên, trên hệ thống khác hay theo benchmark công bố.

Final ban đầu lỗi ghi JSON trước khi lưu metrics. Recovery được phê duyệt chỉ thay wrapper serialization và đã xác minh 40 lượt cùng 8.000 dự đoán. Cần công bố sự cố này trong phần tái lập.

## Phần có thể đưa vào khóa luận

- Thiết lập và công thức. [Phương pháp](METHODOLOGY.md)
- Development, final và kiểm tra tính nhất quán. [Bảng kết quả](RESULTS_TABLES.md)
- Phân biệt quan sát, giả thuyết và trade-off Recall–FPR. [Phân tích](RESULTS_ANALYSIS.md)
- Giới hạn thống kê, prevalence và quy mô. [Tính hợp lệ](THREATS_TO_VALIDITY.md)
- Protocol và recovery. [Tái lập](REPRODUCIBILITY.md)
- Tám biểu đồ cùng dữ liệu nguồn. [Chú thích hình](FIGURE_CAPTIONS.md)
