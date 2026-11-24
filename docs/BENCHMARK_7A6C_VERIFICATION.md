# Kiểm chứng offline 7A.6C

Fixture đối chiếu hợp đồng ba adapter trên Batch 02, 03, 01 theo thứ tự Timeout, Database, Cascade, kiểm HTTP, span graph, Single/Cross và bounded completeness. Fake clock kiểm late Product completion và hết hạn. Chặn approval sai scope, mô phỏng, expiry, replay sau restart, retry sau timeout, telemetry mismatch và context leakage qua các regression hiện có. Fixture activation lỗi kiểm rollback baseline, 0 POST, giữ marker khi rollback lỗi và chặn batch tiếp theo.

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_collection_7a6c.py tests/test_collection_7a6b.py
.\.venv\Scripts\python.exe -B -m tools.collection_readiness_7a6a --batch timeout-a --audit
.\.venv\Scripts\python.exe -B -m tools.audit_research
```

Không chạy fault live. Historical live evidence dùng kiểm contract, không phải live acceptance của đường mới.

19 test adapter/gate đạt. Lần regression đầu có một failure Processing fixture vì Product lookup timeout trước hook. Không sửa fixture. Lần chạy lại đầy đủ đạt 131 test trong 60,26 giây, 3 cảnh báo deprecation. Khớp 18 hash Processing A, 15 hash Normal A, 17/20/21 hash các batch lịch sử và 63/63 fingerprint MeCoLog. Năm CLI dry-run đều ghi 0 POST.
