# Phân tích kết quả

## Quan sát

Trên HDFS final, Binary F1 tăng từ 0,6473 lên 0,7897 và ROC-AUC từ 0,6104 lên 0,9116. Cả hai tăng ở 20/20 cặp seed. Recall tăng 37,75 điểm phần trăm, còn FPR tăng **31,50 điểm phần trăm** và Binary Precision giảm từ 96,03% xuống 73,47%. Development cũng có mức tăng Binary F1 và ROC-AUC, nhưng FPR chỉ tăng 3,25 điểm phần trăm. [Bảng số liệu](RESULTS_TABLES.md)

Một centroid Anomaly phải đại diện cho nhiều biểu hiện. Trong chẩn đoán development, một số Anomaly dài gần prototype Normal hơn prototype Anomaly, trong khi nhóm ngắn có score cao. Khi giữ query, checkpoint và Normal support cố định, thay 5 Anomaly support ngắn bằng 5 support dài làm trung bình 78,65/200 query đổi nhãn và đảo chiều tương quan giữa độ dài và score. Các lượt resampling trước đó cũng cho thấy 19/20 lượt single-prototype 10-shot bỏ sót cả 64 Anomaly dài. [Độ nhạy với support](../support_stability_1000_1019/summary.json) · [Chẩn đoán có kiểm soát](../controlled_diagnostics_1000_1019/summary.json)

## Giả thuyết giải thích

Dùng hai centroid cho phép nhóm Anomaly dài có đại diện riêng. Ở final, Recall nhóm 2–4 giữ 100%, nhóm 20–29 tăng từ 0% lên 80,88%. ROC-AUC tăng chứng tỏ thứ tự score theo cặp Normal–Anomaly được cải thiện trên query đã giữ riêng. Một cơ chế phù hợp với số liệu là một số Anomaly dài nhận cosine cao hơn từ centroid gần chúng. Sự phân tách cũng có thể phản ánh đặc điểm độ dài riêng của HDFS. Cần thêm bằng chứng để liên hệ các centroid với dạng lỗi ngữ nghĩa.

Tại ngưỡng 0, FP trung bình tăng từ 2,65 lên 34,15 mỗi seed, còn FN giảm từ 51 xuống 13,25. Một giả thuyết là một số Normal cũng gần centroid Anomaly dài, nên phép max làm score vượt ngưỡng. Khác biệt support và phân bố nhóm độ dài giữa development và final có thể góp phần. Số liệu hiện có chưa quy mức tăng FPR cho padding, OOV hoặc một yếu tố đơn lẻ. Macro F1 lấy trung bình F1 cả hai lớp. Lợi ích trên Anomaly có thể đi cùng mức giảm trên Normal, phù hợp với việc Macro F1 giảm ở 9/20 seed dù Binary F1 tăng cả 20 seed. [Chênh lệch ghép cặp](../final_recovery_seed123/paired_final_comparison.csv)

## Giới hạn diễn giải

Nhóm 2–4 event có 0 Normal và 49 Anomaly, nhóm 5–19 có 71 Normal và 3 Anomaly, nhóm 20–29 có 23 Normal và 40 Anomaly, nhóm 30–50 có 6 Normal và 8 Anomaly. Hai nhóm nhỏ có độ phân giải thấp. ROC-AUC không được tính cho nhóm 2–4 do thiếu Normal. Phân tích độ dài diễn ra sau kết quả chính và không được dùng để chỉnh quy tắc.

Một split HDFS final với một checkpoint BGL chưa chứng minh khả năng chuyển sang hệ thống khác. Xu hướng F1 và AUC được lặp lại trên pool giữ riêng, còn mức tăng FPR lớn hơn làm hạn chế kết luận tại ngưỡng đã khóa. Điều này chưa đủ để quy cho overfitting development hoặc để loại trừ ảnh hưởng của cấu trúc đặc thù HDFS.
