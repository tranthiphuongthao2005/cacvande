# Khảo sát MeCoLog và ranh giới tích hợp

Project nguồn nằm ở ../tuanmartin-MeCoLog-8c446ac. Project dịch vụ nằm cùng cấp với thư mục nguồn bên trong workspace VS Code.

| Đường dẫn nguồn | Vai trò |
|---|---|
| model.py | Model.encode, ParamEncoder, ParamAwareEncoderLayer, GKI và RoPE. Trả embedding CLS mỗi sequence. |
| Drain.py và preprocess/parsing.py | Drain.LogParser và DrainAdapter. Adapter có định dạng raw BGL/HDFS, fit cây và transform trên cây đã khóa. |
| preprocess/embeddings.py | Local SentenceTransformer distilbert-base-nli-mean-tokens, mean pooling, 768 chiều. Cache theo unique template trong lần chạy. |
| preprocess/parameters.py | Explicit/positional keys, NUM/IP/HEX/PATH/STR, signed log1p, chuẩn hóa path, character IDs, PAD=0, UNK=1, P=8 và C=16. |
| preprocess/datasets.py | BGL window 20/20 và HDFS gom theo BlockId. Ground truth và chia dữ liệu phục vụ benchmark. |
| preprocess/npz_io.py và dataloader.py | Tensor/NPZ, metadata và padding. Dùng làm tham chiếu để kiểm chứng adapter online. |
| meta_train.py, meta_test.py, losses.py, config.py | Entrypoint và objective nghiên cứu. meta_test có I/O ở top level. Hàm prototype và score là tài liệu tham chiếu khi đóng gói inference. |
| real_smoke_cpu/pre_final_audit.py | Hàm seed_support, anomaly_partition, unit_mean và score đã kiểm toán. Single dùng một Anomaly centroid; multi dùng max cosine tới các Anomaly centroid trừ cosine Normal. |
| real_smoke_cpu/final_evaluation.py, final_recovery.py và các thư mục protocol/results | Runner và evidence của final research. Không cần triển khai vào service. |
| docs, tests, .venv | Tài liệu phương pháp, unit tests preprocessing và môi trường nghiên cứu. |

real_smoke_cpu còn có archives, sbert, preprocessed_data, hdfs_locked_features_seed123, meta_smoke_seed123, baseline100_seed123, diagnosis_seed123, support_stability_1000_1019, controlled_diagnostics_1000_1019, prototype_experiments_seed123, pre_final_audit_seed123, final_evaluation_locked_seed123, final_recovery_seed123 và thesis_results.

## Dependency và artifact cho inference sau này

- **Encoder và checkpoint.** Đóng gói một bản nguồn có provenance từ model.py và checkpoint đã duyệt. Đọc checkpoint tin cậy bằng torch.load với weights_only=True, chuyển CPU, nạp state dict net với strict=True, model.eval() và inference_mode(). Kiểm tra 32 tensor và fingerprint. Nguồn baseline cấu hình 1 layer, 8 heads, chiều 768, vocabulary 12 key và 42 ký tự, P=8, C=16.
- **Tiền xử lý.** Torch, NumPy, regex, pandas cho Drain gốc, Sentence Transformers và Transformers cho SBERT local. Giữ revision b404353e5a0ef9cdf6a4500baa81aaec875d4db0 và hash tokenizer/weights. Tách adapter đọc JSON event khỏi parser dataset. Các lệnh training, biểu đồ, scikit-learn metrics, NPZ và nhãn benchmark nằm ngoài runtime API.
- **Vocabulary.** Dùng bảng ánh xạ và checksum đi kèm checkpoint. Giữ nguyên ID OOV và padding. Kích thước giống nhau vẫn có thể sai ánh xạ. Tái fit vocabulary phải được đánh giá như một biến thể có checkpoint tương thích.
- **Prototypes.** Đóng gói các phép tính thuần đã audit thành adapter. Chuẩn hóa embedding theo L2, lấy trung bình support và chuẩn hóa centroid. Baseline dùng cosine Anomaly trừ cosine Normal. Multi chia Anomaly support ≤4 và >4 event, fallback nếu một nhóm có dưới hai mẫu. Nhãn support và độ dài support phải có provenance. Không lấy ngưỡng hay ranh giới độ dài từ final labels.

tools/audit_research.py đối chiếu manifest khóa, SHA-256 checkpoint, chín nguồn Python, NPZ, scorer, các nguồn báo cáo và các đầu ra có fingerprint. File nhị phân và CSV nhạy cảm chỉ được đọc dưới dạng byte để băm. Không parse nhãn final, strict-load checkpoint hay gọi model trong giai đoạn dịch vụ.
