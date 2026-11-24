# Tích hợp MeCoLog

Để strict-load checkpoint BGL 100 episodes seed 123, `app/mecolog_runtime.py` dùng `model.Model` gốc, CPU, `weights_only=True`, state `net`, `strict=True`, 1 layer, 8 heads, 768 chiều, window 50, key vocabulary 12 và character vocabulary 42. Kiểm tra 32 tensor, SHA-256 trước và sau nạp, `eval()` và vô hiệu hóa gradients. Khi đường chấm điểm được duyệt, wrapper gọi `Model.encode` trong `torch.inference_mode()` và kiểm tra output [B,768] hữu hạn. GKI, RoPE và CLS thuộc encoder gốc. APCL là objective huấn luyện và nằm ngoài runtime.

| Thành phần | Phần được dùng |
|---|---|
| `Drain.py`, `preprocess/parsing.py` | Fit lại cây trên đúng tập training HDFS lịch sử để tái dựng, so template/EventId và dùng treeSearch đóng băng |
| `preprocess/parameters.py`, `preprocess/npz_io.py` | Extraction, mã hóa tham số, checksum frozen vocabulary và schema tensor |
| `preprocess/embeddings.py` | SBERT local 768 chiều, mean pooling, CPU, lô 4, cache template trong lượt |
| `preprocess/datasets.py` | Tham chiếu nghiệp vụ HDFS BlockId/BGL window, không đưa nhãn benchmark vào adapter |
| `pre_final_audit.py` | Tham chiếu toán học cho scorer thuần và fallback |

Dependency dịch vụ là Python 3.11, FastAPI, Uvicorn và httpx. Chẩn đoán tính năng ML dùng thêm CPU PyTorch, NumPy, pandas, regex, Sentence Transformers và Transformers có sẵn trong môi trường nghiên cứu. Cấu hình verifier giới hạn Torch hai intra-op thread, một inter-op thread. Nó giải phóng encoder trước khi nạp SBERT để giảm peak RAM và stream log trong archive. Không cần tải artifact mới.

Checkpoint SHA-256 `713d1ec5a4c34d9a091abea9dc2430c0e9500a9255e0bbc7307a6edfa053c5f0`. Vocabulary SHA-256 `087874c66d0fabaeb2ab52cd36d05d6720389f3dc033834f90dac50e1c928e3d`. Snapshot SBERT revision `b404353e5a0ef9cdf6a4500baa81aaec875d4db0`. Hiện có strict-load thực và fixture cho wrapper, còn forward MeCoLog trên trace thật đang bị chặn.
