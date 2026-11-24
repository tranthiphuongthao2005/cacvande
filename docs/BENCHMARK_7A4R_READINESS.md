# Readiness 7A.4-R

**3 technically valid, 3 cơ chế, 0 cấu hình độc lập đã xác minh, 3 cặp, 0 VERIFIED, 0 blind eligible.** Ưu tiên thu campaign mới khi được phép, rà soát độc lập và khóa kế hoạch known-fault trước. Chưa có Batch 04, không gọi hệ thống ứng dụng hoặc OpenAI, không thay đổi lịch sử, không chạy HDFS final hoặc scoring.

Audit xác minh 17/20/21 checksum từng batch, 33 pilot, 9 hồ sơ 7A.2, 4 smoke 7A.3, 4 smoke 7A.3B và 63 fingerprint MeCoLog. Công cụ offline kiểm hash, provenance, scope, pairing, giao cắt ID và chữ ký với lịch sử đã có, tình trạng eligibility và phiếu review. Hai CSV đã tạo và không ghi đè khi chạy lại.

**77/77 pytest đạt** trong 39,13 giây với ba cảnh báo deprecation có sẵn. Regression dùng API test và PostgreSQL lab tách biệt. Sau khi bổ sung đối chiếu ID/chữ ký lịch sử, hai test consolidation và lệnh check-only chạy lại đều đạt.

```powershell
.\.venv\Scripts\python.exe -B -m tools.consolidate_7a4 --check-only
$out = ".\experiments\consolidation_$(Get-Date -Format yyyyMMdd_HHmmss)"
New-Item -ItemType Directory $out
.\.venv\Scripts\python.exe -B -m tools.consolidate_7a4 --output-dir $out
.\.venv\Scripts\python.exe -B -m tools.audit_research
```

[Báo cáo](BENCHMARK_7A4_CONSOLIDATED_REPORT.md) · [Kế hoạch quy mô](BENCHMARK_SAMPLE_SIZE_PLAN.md) · [LLM và Detection readiness](LLM_EVALUATION_READINESS.md)
