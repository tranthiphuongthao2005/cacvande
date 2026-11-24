# Xác minh 7A.5B

Regression với API và PostgreSQL cô lập đạt 95 pytest trong 57,91 giây, có ba cảnh báo deprecation. Sau khi bổ sung assertion log attempt, recovery và matrix, 17 test mục tiêu chạy lại đều đạt. Test replay checksums đọc bundle lịch sử và 63 fingerprint; ba batch xác minh 17, 20 và 21 hash. Pilot 33, 7A.2 9 và hai smoke 4 mỗi bundle. Protocol draft 7A.5A được giữ nguyên; digest file ghi trong collector_validation.json.

Dry-run normal-a trả 0 request, cap 2 POST, 420 giây work và 30 giây cleanup. Fixture thành công gửi hai POST giả lập, preflight hoặc activation lỗi gửi 0, timeout hoặc POST lỗi gửi 1 rồi dừng. Rollback lỗi trả CLEANUP_FAILED và giữ bundle. Test còn từ chối snapshot bị đổi, ground truth lẫn vào context và thiếu event ES. SHA-256 của bundle fixture khớp và nhãn được lưu dưới labels với NEEDS_REVIEW.

Bằng chứng cục bộ gồm normal Order thành công, 503 qua Order, số lượng/thời gian retry và exhausted log, timeout và unavailable phía User, processing hai giai đoạn và recovery khi tắt hook. Các fixture chưa chứng minh độc lập cấu hình ngoài lab.

Chạy từ thư mục thesis-log-anomaly trong PowerShell.

```powershell
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a5b --campaign normal-a
.\.venv\Scripts\python.exe -B -m tools.validate_7a5
.\.venv\Scripts\python.exe -B -m tools.audit_research
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_benchmark_7a5b.py
# Với TEST_PG_ADMIN_URL trỏ PostgreSQL test cô lập
.\.venv\Scripts\python.exe -B -m pytest -q
```
