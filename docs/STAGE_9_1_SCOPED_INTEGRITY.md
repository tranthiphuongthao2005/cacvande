# Stage 9.1 — Scoped integrity

Operator phê duyệt phát triển và kiểm thử Microservices cô lập tại Stage 9.1R.1 trên baseline `b68eba6e98cd36fe07019ab023b10bf169e3a598`. Worktree `thesis-log-anomaly-stage91` dùng branch `feature/microservices-detection`.

## Kiểm tra trước và sau triển khai

Từ worktree trong PowerShell, dùng Python của project để chạy kiểm tra chỉ đọc.

```powershell
$python = "..\thesis-log-anomaly\.venv\Scripts\python.exe"
& $python -B -m tools.check_stage_9_1_integrity
git --no-optional-locks status --short --branch
git diff --check
```

Điều kiện bắt buộc gồm SHA-256 **8/8** frozen, **190/190** cohort, **95/95** acceptance, **63/63** MeCoLog và mọi manifest trong bảng dưới đây. Công cụ kiểm thêm collection plan và các fingerprint cấu hình được plan ghim. Git diff so với baseline kiểm tra cả index lẫn working tree. Chỉ bảy đường dẫn Stage 9.1 được phép thay đổi. Tệp chưa theo dõi `git` có sẵn ở main được bỏ qua khi đọc trạng thái.

Phạm vi bảo vệ gồm code LLM, frozen dataset, evaluation plan, reference labels, scoring protocol, approvals, execution ledgers, full benchmark validator và mọi tệp baseline ngoài phạm vi Stage 9.1. Audit research kiểm tra riêng cây MeCoLog bên cạnh worktree, gồm chín tệp gốc, checkpoint và các artifact HDFS đã được ghim. Dừng khi có digest mới lệch hoặc có thay đổi protected/out-of-scope. JSON và exit code của công cụ ghi riêng mandatory results, known limitations, mismatches và changes.

| Thư mục dưới `experiments/` | Manifest | Số hash khớp |
| --- | --- | ---: |
| `benchmark_7a4_batch01` | `bundle_sha256.json` | 17 |
| `benchmark_7a4_batch02` | `bundle_sha256.json` | 20 |
| `benchmark_7a4_batch03` | `bundle_sha256.json` | 21 |
| `benchmark_7a1_pilot_seed124` | `checksum_manifest.json` | 33 |
| `benchmark_7a2_verification` | `checksum_manifest.json` | 9 |
| `benchmark_7a3_smoke` | `checksum_manifest.json` | 4 |
| `benchmark_7a3b_smoke` | `checksum_manifest.json` | 4 |
| `benchmark_7a5/normal_a_integration_smoke` | `bundle_sha256.json`, `checksum_manifest.json` | 15, 10 |
| `benchmark_7a5/processing_a_development_pilot` | `bundle_sha256.json`, `checksum_manifest.json` | 18, 12 |

Các manifest có thể bao phủ cùng tệp. Danh sách gốc của mốc 88/88 vẫn chưa được xác định, nên giữ `HISTORICAL_SCOPE_UNRESOLVED`.

## Sai lệch LLM đã được ghi nhận

| Tệp | Digest ghim trong evaluation plan | Digest working tree Windows |
| --- | --- | --- |
| `app/llm_analysis.py` | `90decdbaaa527ecf47571bc2485917a6f7291c01ea37c3c1b8a3855fe65c0c1d` | `fc549a9ec718ff9353f1f3dbc36911f407580f592fbb1af38f7fe93a32be2759` |
| `app/llm_provider.py` | `3c3ce219b304f589f7d02afb8b75b3d90fbd94bed108b25e924c9f612c16fc46` | `08611986cdd0dbf546ec6faf9750168d8a181d4563084ea4909fbb9247feeb9c` |

Scoped check đối chiếu nội dung hai tệp LLM với Git blob baseline sau quy đổi CRLF sang LF. Bước này xác minh baseline đã được phê duyệt và giữ trạng thái `LLM_SOURCE_DIGEST_MISMATCH` đối với plan. Full validator vẫn dùng SHA-256 byte gốc và giữ `FULL_LLM_BENCHMARK_INTEGRITY_FAIL`.

Khi tạo worktree, Git trên Windows đã làm đổi line ending của 14 tệp có fingerprint trong collection plan và một draft protocol thuộc benchmark 7A.5. Sau khi từng bản checkout được chứng minh chỉ khác line ending và Git blob khớp cả digest ghim lẫn tệp trên main, các bản checkout trong worktree được đưa về đúng byte của baseline. Scoped check tiếp tục kiểm SHA-256 byte gốc cho các tham chiếu này. Git có thể áp dụng lại chuyển đổi nếu checkout các tệp đó, nên chạy scoped check lại sau khi đổi worktree.
