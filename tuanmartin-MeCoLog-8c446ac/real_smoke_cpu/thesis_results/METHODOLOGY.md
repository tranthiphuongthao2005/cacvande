# Phương pháp nghiên cứu

## Thiết lập và encoder

Checkpoint được meta-train trên BGL trong 100 episode với seed 123, một encoder layer và tám attention head. Hai phương pháp dùng chung encoder MeCoLog nguyên bản và feature HDFS đã khóa ở window 50. GKI, RoPE, Transformer và APCL thuộc baseline gốc. Phân nhóm Anomaly support theo độ dài là phần mở rộng nghiên cứu ở bước suy luận. [Bài báo MeCoLog](https://pmc.ncbi.nlm.nih.gov/articles/PMC13521359/)

## Support sampling và scoring

Với mỗi seed 1000–1019, NumPy default_rng (PCG64) tạo hoán vị không hoàn lại cho Normal trước, Anomaly sau. Lấy 10 hàng đầu mỗi lớp theo thứ tự pool đã khóa. Hai phương pháp dùng cùng support IDs trong từng seed, và query pool 200 session giữ cố định trong mỗi split. Nhãn query chỉ dùng khi chấm điểm.

Gọi $z_i=\operatorname{L2Norm}(f_\theta(x_i,p_i))$. Với support group $S$, centroid là $c(S)=\operatorname{L2Norm}(|S|^{-1}\sum_{i\in S} z_i)$. Single-Prototype dùng $c(N)$ và một $c(A)$ trên toàn bộ Anomaly support. Length-Aware Multi-Prototype giữ cùng $c(N)$, chia Anomaly support thành nhóm ≤4 và >4 event theo true length từ manifest. Ranh giới 4 event hình thành trên development và được khóa trước final. Nếu một nhóm có dưới hai mẫu, dùng một centroid trên toàn bộ Anomaly support.

Score của query là $s_q=\max_j(z_q^\top c(A_j))-z_q^\top c(N)$. Single-Prototype dùng một phần tử trong phép max. Dự đoán Anomaly khi $s_q>0$. Scorer chỉ dùng embedding query, các centroid đã dựng và ngưỡng 0. Encoder có thể mang tín hiệu độ dài và padding trong embedding. [Đặc tả khóa](../pre_final_audit_seed123/PROTOCOL.md)

## Chi phí tính toán

Với hai Anomaly centroid, số phép cosine tăng từ hai lên ba mỗi query. Bộ centroid float32 768 chiều tăng từ 6 KiB lên 9 KiB. Chi phí bổ sung nằm ở phân nhóm support và scoring. Encoder giữ nguyên. Trong phép đo vi mô development 10-shot ngẫu nhiên trên 200 embeddings đã cache, dựng centroid và chấm điểm mất trung bình 0,40 ms cho Single-Prototype và 0,82 ms cho Multi-Prototype chia theo độ dài. [Số đo](../prototype_experiments_seed123/experiment_summary.json)
