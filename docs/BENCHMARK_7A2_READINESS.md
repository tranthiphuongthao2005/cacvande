# Readiness 7A.2

| Hạng mục | Kết quả |
|---|---|
| Telemetry | 4 root span hoàn tất, 16/16 event khớp, chưa có source seal/ingestion receipt. |
| Ground truth | 4 hồ sơ đủ cho review ứng viên, 0 nhãn VERIFIED và 4 nhãn gốc UNVERIFIED. |
| Human review | 4 NEEDS_REVIEW, 0 VERIFIED, 0 REJECTED, 0 INCONCLUSIVE do chưa có quyết định của reviewer. |
| Độc lập | Một campaign đã dùng để phát triển, 0 trace blind-eligible. |
| Pairing | 4/4 cặp đã kiểm hash và scope; Cross 4 PARTIAL, Single 4 UNKNOWN trước và sau. |

Không mở rộng collection. Detection vẫn NOT_READY_FOR_SCORING. Không gọi OpenAI hoặc mở HDFS final. Xác minh 33 file pilot và 63 fingerprint nghiên cứu. [Audit và tham chiếu snapshot gốc](../experiments/benchmark_7a2_verification/audit.json) · [Checksum mới](../experiments/benchmark_7a2_verification/checksum_manifest.json)

Regression đạt **60/60 pytest** trong 46,64 giây, gồm PostgreSQL lab riêng và ba bài 7A.2. Các fixture bao phủ phiếu reviewer, đồ thị span, receipt đến muộn, thiếu marker/child span, snapshot bị truncate, isolation và khả năng tái lập. Có ba cảnh báo deprecation có sẵn. Chạy lại audit tạo chín artifact khớp checksum.

```powershell
$stamp = Get-Date -Format yyyyMMdd_HHmmss
.\.venv\Scripts\python.exe -B -m tools.verify_ground_truth_7a2 --output ".\experiments\benchmark_7a2_$stamp"
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_ground_truth_7a2.py
.\.venv\Scripts\python.exe -B -m tools.audit_research
```

Để kiểm một phiếu thật, chạy `tools.verify_ground_truth_7a2 --review <file-quyết-định> --dossier <file-dossier>`. Việc kiểm phiếu chỉ đọc artifact. Các điều kiện bắt buộc còn thiếu gồm reviewer độc lập, source seal/ingestion receipt thật và cohort độc lập chưa từng xem.
