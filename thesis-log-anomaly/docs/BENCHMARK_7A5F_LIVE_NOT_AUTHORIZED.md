# 7A.5F — LIVE_NOT_AUTHORIZED

Approval gate chỉ tìm thấy operator_approval_template.json ở trạng thái PENDING trong workspace. Yêu cầu 7A.5F chưa cung cấp đường dẫn tới một approval riêng do operator cấp. Dry-run ghi 0 POST, cap 1 POST, cutoff dự kiến 420 giây sau response và ngân sách tổng 792 giây. CLI từ chối mẫu PENDING với exit code 2 trước khi tạo output. Chưa có thời điểm hết hạn hoặc provenance của approval live để kiểm tra.

| Hạng mục live | Kết quả |
|---|---|
| POST thực, HTTP status và latency | 0 POST, không có giá trị live |
| Preflight, fault activation và rollback | Chưa chạy |
| Producer / Docker / Elasticsearch, flush và handoff | Chưa đo |
| Single/Cross, completeness và snapshot checksum | Chưa tạo |
| Deadline live | Chưa đo, chỉ kiểm fixture |
| Ground truth mới và blind eligibility | 0 VERIFIED, 0 blind-eligible |

Regression trên PostgreSQL cô lập đạt 107 pytest trong 52,78 giây với 3 cảnh báo deprecation. Fixture kiểm gate, deadline với đồng hồ giả, fault path, request cap và no retry, reconciliation, rollback, pairing và ground truth isolation. Kiểm toán offline khớp 15 checksum Normal A, 17/20/21 checksum ba batch, 33 checksum pilot, 9 checksum review 7A.2, 4 checksum mỗi smoke 7A.3 và 7A.3B, và 63/63 fingerprint MeCoLog. Không có bundle Processing A mới.

Chạy từ thư mục thesis-log-anomaly trong PowerShell.

```powershell
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a5e --campaign processing-a-development-pilot
.\.venv\Scripts\python.exe -B -m tools.validate_7a5d
```

Điều kiện để chạy live là operator cấp approval riêng đúng campaign, configuration, cap 1 POST, scope Order/processing, rollback plan và output mới. Lệnh live đã ghi trong BENCHMARK_7A5E_VERIFICATION.md. Dừng ở 7A.5F.
