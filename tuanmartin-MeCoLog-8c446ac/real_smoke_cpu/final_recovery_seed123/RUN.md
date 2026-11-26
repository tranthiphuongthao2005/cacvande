# Chạy recovery đã được phê duyệt

Lệnh thực tế chạy từ thư mục có model.py.

```powershell
$env:OMP_NUM_THREADS = '2'
$env:MKL_NUM_THREADS = '2'
.\.venv\Scripts\python.exe -B .\real_smoke_cpu\final_recovery.py
```

Wrapper kiểm tra incident và hash runner gốc, rồi chạy fixture trước preflight. Trước khi nạp mảng final, runner tạo thư mục riêng và ghi recovery_preflight.json, serialization_fixture_test.json và serialization_patch_diff.txt. Các phép tính tiếp tục qua cùng runner gốc và scorer đã khóa. Wrapper đọc lại artifact để hậu kiểm rồi ghi recovery_manifest.json.

Lệnh trên ghi nhận cách chạy đã hoàn thành. Chốt một lượt từ chối chạy lại khi thư mục recovery tồn tại. Giữ nguyên cả thư mục sự cố và thư mục recovery. Có thể đọc lại các CSV/JSON mà không chạy inference.
