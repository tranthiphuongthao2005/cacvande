# Thiết kế preprocessing BGL → HDFS

Pipeline độc lập đọc tập con có nhãn, chia split, tạo cây Drain, mã hóa template và tham số, rồi xuất mảng tương thích với MeCoLog. Cả chín file Python của archive được giữ nguyên.

| Module | Dữ liệu xử lý |
|---|---|
| datasets | BGL window 20/20 theo thứ tự gốc. HDFS session theo BlockId bằng ground truth chính thức. |
| parsing | Cây Drain theo từng domain, threshold 0.5 và depth 4. Giữ line ID gốc, EventId và EventTemplate. |
| parameters | Explicit key theo cú pháp key=value, positional key theo thứ tự, 5 kiểu tham số, OOV và tensor tham số. |
| embeddings | Local snapshot SBERT trên CPU, frozen, batch nhỏ, cache các unique template trong một lần chạy. |
| npz_io | Xuất dense NPZ và kiểm tra dtype, shape, chỉ số, nhãn và giá trị hữu hạn. |
| CLI | Tạo bốn file NPZ, hai file mapping JSONL và manifest. Chỉ dùng thư mục output mới. |

Bài báo mô tả Drain 0.5/4, BGL window/stride 20, HDFS grouping theo BlockId, SBERT distilbert-base-nli-mean-tokens với 768 chiều, Hybrid Parameter Embedding, và tỷ lệ train/test 80/20. [Bài báo](https://pmc.ncbi.nlm.nih.gov/articles/PMC13521359/)

| Trường | Shape và dtype |
|---|---|
| x | N × W × 768, float32 |
| y | N × 2, uint8 one-hot, thứ tự Normal và Anomaly |
| p_key, p_type | N × W × 8, int64 |
| p_val | N × W × 8 × 16, int64 |
| p_num | N × W × 8, float32 |
| key_vocab_size, char_vocab_size, max_params, max_chars | Scalar int64 |

W bằng 20 với BGL và 50 với HDFS. Với HDFS, manifest giữ lineage toàn session và mảng model giữ 50 event đầu nếu session dài hơn. Padding thêm ở cuối. Giữ cả bốn tensor tham số cho mọi split.

Manifest chỉ được ghi sau khi hoàn tất xuất bốn split. Khi một lần chạy thất bại giữa chừng, dùng thư mục mới cho lần chạy tiếp theo. File NPZ được xác thực trước khi ghi. Mapping JSONL liên kết line ID tính từ 1 tại file raw của từng domain, EventId và EventTemplate. Manifest lưu path đầu vào, seed, thống kê lớp, số session bị loại và bảng vocabulary có checksum.
