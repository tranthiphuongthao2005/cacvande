# Kế hoạch live acceptance 7A.6C

Thứ tự Normal A → Processing A → Timeout A → Database A → Cascade A. Mỗi lượt có approval thực riêng, một POST, không retry, output mới. Ngừng chuỗi khi lỗi; rollback lỗi giữ marker và chặn lượt kế tiếp. Mỗi lượt DEVELOPMENT_ACCEPTANCE, loại khỏi blind cohort.

Từ thesis-log-anomaly, dùng đúng governance file operator cấp cho từng slug, với 792 giây và output tương đối trùng approval. CAMPAIGN ID lần lượt là normal-a, processing-a-development-pilot, timeout-a-development-acceptance, database-a-development-acceptance và cascade-a-development-acceptance. Approval cần giữ scopes/hashes theo 7A.6A, 32-hex approval ID duy nhất, expiry có timezone và provenance operator. Không dùng approval lịch sử.

```powershell
# Mỗi lệnh chỉ chạy trong lượt được operator duyệt riêng. Đường dẫn approval là ví dụ.
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a6c --configuration normal-a --live --governance C:\approvals\normal-a.json --output .\experiments\benchmark_7a5\accept_normal_a
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a6c --configuration processing-a --live --governance C:\approvals\processing-a.json --output .\experiments\benchmark_7a5\accept_processing_a
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a6c --configuration timeout-a --live --governance C:\approvals\timeout-a.json --output .\experiments\benchmark_7a5\accept_timeout_a
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a6c --configuration database-a --live --governance C:\approvals\database-a.json --output .\experiments\benchmark_7a5\accept_database_a
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a6c --configuration cascade-a --live --governance C:\approvals\cascade-a.json --output .\experiments\benchmark_7a5\accept_cascade_a
```

Bỏ --live, --governance và --output để dry-run. Trước mỗi lần live kiểm Docker, API/DB/ES readiness, fault flags, scope, ledger, tài nguyên và rollback plan. Sau POST kiểm HTTP, receipt, cutoff và postflight, không tự phê duyệt reviewer.
