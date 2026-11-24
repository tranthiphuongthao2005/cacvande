# Batch 02 — Timeout có kiểm soát

Trace `2a6888b936b58eb8760c40d8f2ec1633`, run `2ffef988d50840d5b59495263fd42c7d`. Đã gửi một GET lấy tham chiếu Order lab và **một request đo**. Probe /ready là thao tác pre/postflight riêng. Không replay request đo.

## Fault activation

Order gọi User rồi Product. Dùng fault mode delay có sẵn, đọc runtime flags trực tiếp từ container. Product chạy `LAB_FAULT=delay`, timeout base 2,0 giây, code chờ thêm 0,25 giây. Order có timeout 2,0 giây, một attempt. Oracle từ cấu hình lab hiện có dự kiến HTTP 504 và dependency_timeout. Request thực trả **504 / dependency_timeout**, thời gian client **2.734 ms**.

User trả 200. Order ghi đúng một dependency_attempt_failed với Product và mã dependency_timeout, sau đó dependency_exhausted và completion 504. Product hoàn thành 200 khoảng 252 ms sau completion Order. Span/parent lineage và timestamps trong telemetry giữ quan hệ của lần gọi. Product 200 là completion muộn ở server; không mâu thuẫn với Order đã hết thời gian chờ.

| Chỉ số | Kết quả |
|---|---|
| Run đo / technically valid | 1 / 1 |
| Producer / Docker / ES | 5 / 5 / 5, nội dung và ID khớp |
| Missing / unexpected / duplicate / late sau seal | 0 / 0 / 0 / 0 |
| Flush và bàn giao | 5/5 flush ở cả hai sink; Filebeat handoff UNCONFIRMED |
| Scope Single / Cross | Order 3 event UNKNOWN / 5 event PARTIAL |
| Ground truth | 1 NEEDS_REVIEW, 0 VERIFIED |
| Blind eligible | 0 |

Dossier lưu giả thuyết Product lookup vượt deadline Order, evidence và bước còn thiếu. Phiếu reviewer chưa có danh tính, thời điểm, quyết định hay chữ ký. Snapshot manifest có Pair ID và hai SHA-256, và receipt gắn với producer seal. Không nâng TRACE_COMPLETE.

## Độc lập

Một execution mới và một cấu hình quan sát. Không trùng trace/event ID với pilot hoặc Batch 01. Timeout khác Cascade Product unavailable về cơ chế, nhưng cùng workload serial Order lookup và cùng tập template với Batch 01 (Jaccard 1,0). Không trùng chữ ký có status với Batch 01 hoặc bốn run pilot 7A.1. Chữ ký đó trùng hai timeout lịch sử 7A, nên không có cơ chế mới so với lịch sử và chưa xác minh configuration độc lập. Run nằm ngoài evaluation vì nhãn chờ review, overlap lịch sử và chưa có khóa đã phê duyệt.

## Preflight và rollback

Compose 5.0.2. Docker VM 5,788 GiB, ổ workspace trống khoảng 58,48 GiB trước thu. ES mở PIT thành công trước và sau.

| RAM container | Trước | Sau |
|---|---:|---:|
| Order | 46,30 MiB | 47,31 MiB |
| Product | 46,81 MiB | 47,12 MiB |
| Elasticsearch | 317,4 MiB | 320,2 MiB |
| Context | 23,15 MiB | 21,98 MiB |

Rollback đạt. User, Product và Order trả 200 tại /ready. Runtime không còn LAB_FAULT, LAB_ENABLED hoặc ACCOUNTING_TRACE_ID ở ba service. Volume được giữ nguyên.

**74/74 pytest** trong 51,91 giây, gồm PostgreSQL lab riêng, với ba cảnh báo deprecation có sẵn. Kiểm lại **20 checksum Batch 02, 17 Batch 01 và 63 fingerprint MeCoLog**. Audit 7A tái lập đúng. Detection NOT_READY_FOR_SCORING. Không có OpenAI call, HDFS final, notification hoặc Batch 03.

[Bundle Batch 02](../experiments/benchmark_7a4_batch02/) · [Manifest cặp](../experiments/benchmark_7a4_batch02/snapshot_manifest.json) · [Eligibility](../experiments/benchmark_7a4_batch02/evaluation_candidates.json)

```powershell
$stamp = Get-Date -Format yyyyMMdd_HHmmss
$out = ".\experiments\benchmark_7a4_timeout_$stamp"
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a4 --scenario timeout --output $out
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a4 --execute-lab --scenario timeout --output $out
.\.venv\Scripts\python.exe -B -m tools.audit_research
```

Điều kiện còn thiếu cho evaluation gồm review độc lập, cấu hình/campaign đa dạng hơn, kiểm tra contamination và phê duyệt protocol. Chưa có ACK Filebeat theo event.
