# MeCoLog BGL → HDFS, forward trên CPU

Chạy từ thư mục chứa model.py. Workspace ban đầu có khoảng 62 GiB ổ đĩa trống, 7,68 GiB RAM vật lý và 1,14 GiB RAM khả dụng tại thời điểm đo. Dữ liệu đầu vào được đọc trực tiếp từ ZIP.

```powershell
$python = '.\.venv\Scripts\python.exe'
& $python -B .\real_smoke_cpu\acquire.py
& $python -B .\real_smoke_cpu\run.py inspect-bgl --bgl-start-line 1 --bgl-candidates 8 |
  Tee-Object -FilePath .\real_smoke_cpu\bgl_preflight.jsonl
$env:OMP_NUM_THREADS = '2'
$env:MKL_NUM_THREADS = '2'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
& $python -B .\real_smoke_cpu\run.py preprocess --bgl-start-line 15361 |
  Tee-Object -FilePath .\real_smoke_cpu\preprocessing.log
& $python -B .\real_smoke_cpu\run.py validate |
  Tee-Object -FilePath .\real_smoke_cpu\forward.log
```

Bỏ lệnh acquire khi hai ZIP, local snapshot và provenance.json đã xác minh tồn tại. Để chạy lại vào thư mục mới, truyền cùng đối số --output cho preprocess và validate, ví dụ .\real_smoke_cpu\preprocessed_repeat. Thư mục xuất phải chưa tồn tại khi gọi preprocess.

Lần tải đầu dùng URL giao diện Zenodo cho ZIP. Hai tiến trình curl bị đình trệ và được dừng. Tải lại qua API chính thức của cùng record. HDFS tiếp tục bằng HTTP Range từ byte 79.945.728 sau khi lần tải trực tiếp chậm lại. Hai ZIP được kiểm tra byte count và MD5. SBERT giữ revision b404353e5a0ef9cdf6a4500baa81aaec875d4db0. Chỉ lấy safetensors và cấu hình/tokenizer cần thiết. provenance.json ghi nguồn, checksum, lệnh curl ở lượt hoàn tất và thời gian xác minh theo file.

Chọn lát BGL đầu tiên đủ lớp trong các lát 256 window liên tục, theo nhãn Loghub và trước khi chạy model. Các lát bắt đầu ở dòng 1, 5121 và 10241 đều có 204 Normal và 0 Anomaly trong train. Lát được chọn bắt đầu ở dòng 15361. HDFS dùng 256 block được chọn có phân tầng với seed 123, giữ toàn bộ dòng gốc mỗi block trong lineage. HDFS giữ tối đa 50 event đầu cho tensor model.

Preprocessing chạy SBERT batch 4. Forward khởi tạo một encoder gốc ở chế độ eval, một layer, seed 123 và hai thread CPU. Mỗi domain chọn hai support và một query mỗi lớp theo thứ tự manifest, không dùng lặp ID. APCL dùng temperature 0.07. Lệnh validate kiểm tra lại nhãn và lineage HDFS từ archive bằng lần quét độc lập rồi mới nạp model. Forward và loss dùng để kiểm tra tính hữu hạn. Không có bước tối ưu weights hoặc đánh giá chất lượng.

Kết quả nằm trong preprocessed_data/manifest.json và preprocessed_data/validation.json.
