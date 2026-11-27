# Kế hoạch smoke test CPU trên PowerShell

Chạy từ thư mục chứa model.py. Bước preprocessing cần BGL.log, HDFS.log, anomaly_label.csv và local snapshot SBERT. Nguồn Loghub niêm yết BGL.zip 57,5 MB và HDFS_v1.zip 186,6 MB. SBERT safetensors khoảng 265 MB. CLI chỉ đọc nguồn cục bộ. [Loghub](https://zenodo.org/records/8196385) · [SBERT](https://huggingface.co/sentence-transformers/distilbert-base-nli-mean-tokens/blob/main/model.safetensors)

```powershell
$python = '.\.venv\Scripts\python.exe'
$env:OMP_NUM_THREADS = '2'
$env:MKL_NUM_THREADS = '2'
& $python -B -m unittest discover -s tests -v
& $python -B -m preprocess --help
& $python -B -m preprocess `
  --bgl-log '.\log_data\BGL.log' `
  --hdfs-log '.\log_data\HDFS.log' `
  --hdfs-labels '.\log_data\anomaly_label.csv' `
  --sbert-dir '.\models\sbert-local' `
  --output '.\smoke_run\preprocessed_data' `
  --max-sequences 256 --seed 123 --embedding-batch-size 8
```

Nếu lát BGL đầu thiếu alert, chọn lát bắt đầu bằng --bgl-start-line với ID dòng bằng 1 cộng bội số 20. Mặc định CLI giữ tối đa 50.000 lượt gán dòng vào session HDFS và giới hạn exporter là 2.048 sequence mỗi domain để bảo vệ RAM. File log được đọc tuần tự. CLI in số mẫu từng lớp trước khi nạp SBERT, ghi thời gian và peak working set của tiến trình trên Windows vào manifest. Nếu một lớp có dưới ba sequence trong BGL train hoặc HDFS test, mở rộng tập con với cùng quy tắc rồi kiểm tra lại.

Các bước dưới đây dành cho lượt chạy thực nghiệm đã được phê duyệt. Sau khi manifest và lineage đã kiểm tra, chạy hai entrypoint gốc trong thư mục smoke_run để checkpoint và kết quả thử nằm riêng. Dùng đường dẫn checkpoint thật do lệnh train tạo.

```powershell
Push-Location '.\smoke_run'
try {
  & '..\.venv\Scripts\python.exe' -B '..\meta_train.py' --log_name BGL --window_size 20 --episodes 2 --k_norm 2 --k_anom 2 --m_query 1 --temperature 0.07 --lr 1e-5 --tag smoke --viz 0
  if ($LASTEXITCODE -ne 0) { throw 'Smoke training failed' }
  $checkpoint = Get-ChildItem -LiteralPath '.\checkpoints' -Filter '*_smoke-latest.pt' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (!$checkpoint) { throw 'No smoke checkpoint found' }
  & '..\.venv\Scripts\python.exe' -B '..\meta_test.py' --pretrained_log_name BGL --log_name HDFS --window_size 50 --support_include_anomaly --support_size 4 --query_size 0 --episodes 1 --batch_size 8 --viz 0 --load_path $checkpoint.FullName
  if ($LASTEXITCODE -ne 0) { throw 'Smoke evaluation failed' }
} finally {
  Pop-Location
}
```

Kiểm tra log nạp checkpoint, support có đúng 2 mẫu mỗi lớp và query còn cả hai lớp. Ghi thời gian, RAM, shape, APCL và metrics theo từng lần chạy. Hai episode và checkpoint smoke chỉ dùng để kiểm chứng đường chạy. Bài báo dùng 2.000 episode, 20 support mỗi lớp và 10 query mỗi lớp khi train.
