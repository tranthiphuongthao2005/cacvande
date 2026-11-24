# Batch 03 — Database failure có kiểm soát

Run `a3d1d1c17b614690a9154d7931161e8f`, trace `191b1d0421dae17a8616edddd15bf12d`. Hai request nghiệp vụ gồm một GET tham chiếu Order và một POST đo. Probe readiness phục vụ preflight/rollback riêng. Không replay POST.

Order sở hữu PostgreSQL Order. Fault `LAB_FAULT=database` thay DSN của repository cho request bằng đích loopback không khả dụng. DSN startup giữ nguyên. Luồng POST đã lookup User và Product thành công, sau đó repository không kết nối được trước bước INSERT. Handler lỗi kết nối ghi `database_connection_failed` ở Order và trả **503 / database_unavailable** sau **828 ms** tính từ client. Root Order SERVER kết thúc và có bốn parent link trong scope. User và Product đều trả 200; lỗi biểu hiện ở API Order, không có bằng chứng lan sang hai dependency. Không dừng PostgreSQL và không xóa volume.

| Kiểm tra | Kết quả |
|---|---|
| Lượt đo / technically valid | 1 / 1 |
| Producer / Docker / Elasticsearch | 4 / 4 / 4, ID và nội dung khớp |
| Thiếu, trùng, unexpected, late | 0 trong phạm vi thu |
| Flush | 4/4 ở cả hai sink; không có lỗi |
| Filebeat handoff | UNCONFIRMED |
| Single / Cross | 2 event Order UNKNOWN / 4 event PARTIAL |
| Ground truth | 1 NEEDS_REVIEW, 0 VERIFIED |
| Blind eligible | 0 |

Receipt và provenance đã được đối chiếu ngoại tuyến với snapshot thật. Cặp có event ID, checksum, scope và completeness. Dossier và mẫu review ở thư mục labels, không được đưa vào snapshot.

## Độc lập và rollback

Một execution mới, một cấu hình quan sát, chưa xác minh cấu hình độc lập. Cơ chế lỗi DB khác Cascade 01 và Timeout 02, workload vẫn dùng tham chiếu Order lab và cùng topology. Không trùng trace/event ID với pilot và hai batch trước. Tập template có Jaccard 0,5 với Batch 01 và 02, chữ ký có status khác. Chữ ký trùng hai run trong audit lịch sử 7A. Run nằm ngoài evaluation do overlap, chờ reviewer và protocol chưa khóa.

User/Product/Order đều trả 200 tại /ready sau rollback. Ba container PostgreSQL healthy trước và sau. ES mở PIT thành công và không còn fault flags hoặc accounting scope trong runtime ba API.

| RAM container | Trước | Sau |
|---|---:|---:|
| Order | 47,32 MiB | 46,40 MiB |
| Order PostgreSQL | 17,28 MiB | 18,24 MiB |
| Elasticsearch | 305,1 MiB | 310,6 MiB |
| Context | 17,34 MiB | 16,86 MiB |

Docker VM 5,788 GiB. **75/75 pytest** (53,32 giây), ba cảnh báo deprecation có sẵn. Khớp 21 checksum Batch 03, 20 Batch 02, 17 Batch 01 và 63 fingerprint MeCoLog. Audit 7A tái lập giống artifact lịch sử. Detection vẫn NOT_READY_FOR_SCORING. Không gọi OpenAI, gửi notification, khóa benchmark hoặc chạy Batch 04.

[Bundle Batch 03](../experiments/benchmark_7a4_batch03/) · [Snapshot manifest](../experiments/benchmark_7a4_batch03/snapshot_manifest.json) · [Provenance](../experiments/benchmark_7a4_batch03/completeness_provenance.json)

```powershell
$stamp = Get-Date -Format yyyyMMdd_HHmmss
$out = ".\experiments\benchmark_7a4_database_$stamp"
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a4 --scenario database --output $out
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a4 --execute-lab --scenario database --output $out
.\.venv\Scripts\python.exe -B -m tools.audit_research
```

Các blocker evaluation còn lại là nhãn độc lập, cấu hình/campaign thực sự độc lập và phê duyệt protocol. Chưa có ACK Filebeat theo event.
