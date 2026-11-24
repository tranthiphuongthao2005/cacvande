# Kiểm tra 7A.5E

Dry-run trả LIVE_NOT_AUTHORIZED và 0 POST. Live flag thiếu approval và mẫu PENDING bị từ chối. Reviewer provenance, fixture activation, processing HTTP 500, request cap, no POST retry, rollback, pairing, ground truth isolation và decision import được kiểm offline. Không gửi request tới stack nghiệp vụ.

Regression PostgreSQL cô lập đạt 107 test, 3 cảnh báo deprecation, trong 52,40 giây. 26 test mục tiêu đạt. Audit khớp 15 checksum smoke Normal A, 17/20/21 checksum ba batch, 33 checksum pilot, 9 checksum review 7A.2, 4 checksum mỗi smoke cũ và 63 fingerprint MeCoLog.

Từ thư mục thesis-log-anomaly trong PowerShell.

```powershell
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a5e --campaign processing-a-development-pilot
.\.venv\Scripts\python.exe -B -m tools.validate_7a5d
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_benchmark_7a5e.py
```

Sau khi operator cấp file riêng, dùng đúng output đã ghi trong approval.

```powershell
$approvalPath = 'C:\path\to\operator-approved-processing-a.json'
$outputDir = '.\experiments\benchmark_7a5\processing_a_development_pilot'
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a5e --campaign processing-a-development-pilot --live --max-requests 1 --approval-file $approvalPath --output $outputDir
```
