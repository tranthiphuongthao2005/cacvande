# Lệnh đã thực hiện

Từ thư mục có model.py, dùng CPU và hai thread.

```powershell
$env:OMP_NUM_THREADS = '2'
$env:MKL_NUM_THREADS = '2'
.\.venv\Scripts\python.exe -B .\real_smoke_cpu\final_evaluation.py --preflight-only
.\.venv\Scripts\python.exe -B .\real_smoke_cpu\final_evaluation.py
```

Lệnh preflight-only đã qua mà chưa nạp mảng final. Lệnh thứ hai là lần final duy nhất và trả exit code 1 sau khi đã mở dữ liệu. Không tái chạy hai lệnh trên để phục hồi kết quả. Runner từ chối thư mục output đã được giữ làm audit trail. Xem FINAL_REPORT.md và incident.json trước khi quyết định quy trình recovery.
