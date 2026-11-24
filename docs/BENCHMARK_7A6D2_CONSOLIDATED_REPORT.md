# Báo cáo tổng hợp 7A.6D.2

Chuỗi đã hoàn tất 5/5 adapter LIVE_VERIFIED sau ổn định runtime. Lượt trước dừng tại GET User 127.0.0.1:8011/ready timeout 4,007 giây trước activation, không có POST từ lần bị chặn.

| Adapter | Campaign | Trace ID | Expected HTTP | Actual HTTP | Latency nghiệp vụ | POST | Producer / Docker / ES | Single / Cross | Completeness | Rollback | Postflight | Integrity | Trạng thái |
|---|---|---|---:|---:|---|---:|---|---|---|---|---|---|---|
| normal-a | normal-a | `6f8ebf6c42c1ac858b7f7bb4fbb037d4` | 201 | 1063 ms | 1 | 3 / 3 / 3 | 1 / 3 | UNKNOWN / PARTIAL | PASS | Bốn HTTP 200 | 19/19 | LIVE_VERIFIED |
| processing-a | processing-a-development-pilot | `fdb6d9972451e67b048563fea2d7b356` | 500 | 234 ms | 1 | 4 / 4 / 4 | 2 / 4 | UNKNOWN / PARTIAL | PASS | Bốn HTTP 200 | 19/19 | LIVE_VERIFIED |
| timeout-a | timeout-a-development-acceptance | `74b0d4d13751da1586ef23c732c2a914` | 504 | 2157 ms | 1 | 5 / 5 / 5 | 3 / 5 | UNKNOWN / PARTIAL | PASS | Bốn HTTP 200 | 19/19 | LIVE_VERIFIED |
| database-a | database-a-development-acceptance | `30a7627f08093788e70711e05d85dad3` | 503 | 140 ms | 1 | 4 / 4 / 4 | 2 / 4 | UNKNOWN / PARTIAL | PASS | Bốn HTTP 200 | 19/19 | LIVE_VERIFIED |
| cascade-a | cascade-a-development-acceptance | `8cc314768cf9c12e300243a20669ad28` | 502 | 141 ms | 1 | 5 / 5 / 5 | 3 / 5 | UNKNOWN / PARTIAL | PASS | Bốn HTTP 200 | 19/19 | LIVE_VERIFIED |

Tổng 5/5 LIVE_VERIFIED, 5 POST trong toàn giai đoạn và 4 POST mới trong lượt này, 0 retry. 21 event distinct khớp giữa ba nguồn, trong đó 18 event từ bốn lượt mới. Mỗi lượt giữ DEVELOPMENT_ACCEPTANCE, TRACE_COMPLETE=false, handoff UNCONFIRMED và dossier NEEDS_REVIEW. 0 ground truth VERIFIED, 0 độc lập VERIFIED và 0 blind-eligible.

Bốn bộ governance đã cấp có ràng buộc SHA-256 và approval ID riêng. Cả bốn đạt 5/5 readiness gate và PostGate. Taxonomy/protocol dùng lại evidence chung đã xác minh. Mỗi approval ID đã consume đúng một lần, hash governance và scope khớp ledger. Audit khớp 95/95 hash của năm acceptance bundles, 18 hash Processing pilot, 15 hash Normal smoke, 17/20/21 ba batch lịch sử và 63/63 fingerprint MeCoLog.

Trước 7A.7 cần phê duyệt đợt collection mới, xác minh grouping và độc lập cấu hình, gắn split/campaign độc lập và chuẩn bị reviewer. Không đưa các lượt development acceptance vào blind set.

Hậu kiểm lượt trước từng thấy Product timeout 4,008 s. Kết quả hậu kiểm lượt hoàn tất được ghi bên dưới.

## Runtime Stabilization

Máy có 8.241.881.088 byte RAM vật lý. Docker Desktop dùng WSL2, Engine thấy 4 CPU và 6.215.159.808 byte RAM. Không đổi giới hạn. Probe tài nguyên trước/sau stop ghi CPU host 76% → 28%, RAM khả dụng 490.768 → 437.856 KiB, I/O đĩa 100,44 → 93,43 MB/s, C còn khoảng 62,31 GB. Đây là các mẫu tức thời, không suy ra tăng RAM trống. Trước stop autoscale-demo-control-plane dùng 246,64% CPU Docker và 2,098 GiB, Kibana và n8n khoảng 502,5 và 341,4 MiB. Demo nằm ở mạng kind riêng, ba API/Context/ES nằm ở mạng project riêng. Core giữ nguyên. Không thấy pytest đang chạy; các process PostgreSQL Windows đã thấy không mang đường dẫn .pg-test, nên giữ nguyên.

Tạm dừng Kibana, n8n, LLM Analysis, Incident Adapter, Detection và autoscale-demo-control-plane bằng docker stop. Không xóa container hoặc volume. User/Product/Order và ba DB, Elasticsearch, Filebeat, Context là tập bắt buộc theo collector runtime. Không chạy regression đồng thời với 40 probe và acceptance.

Host baseline GET /health và /ready đều 200 tại thời điểm đo. Readiness User/Product/Order/Context lần lượt 400,8/139,7/480,3/930,1 ms. Probe tại container sau rollback Processing có /health 10,2–16,6 ms; /ready User/Product/Order 16,2/13,0/22,3 ms, Context 287,7 ms. Kết nối PostgreSQL 10,1–12,9 ms; SELECT 1 mất 0,001 giây xấp xỉ. Order→User/Product qua mạng nội bộ 5,0/4,5 ms. Context credential trả HTTP 403 khi GET ES root, chứng minh kết nối HTTP và scope hẹp ở endpoint quản trị này; /ready dùng PIT và trả 200. Ba API /ready thực hiện mở kết nối DB và SELECT 1; Context mở/đóng PIT. Không sửa endpoint hoặc timeout.

Stability duy nhất bắt đầu 12:50:24 UTC và kết thúc 12:51:56 UTC. 10 vòng, 40/40 HTTP 200, không timeout, không probe ≥3,5 s; min/median/max 9,637/16,641/579,132 ms. Nghỉ 10 giây giữa vòng. Preflight Processing 12:51:59 UTC đạt bốn HTTP 200 và health/flags/marker. Kết quả phù hợp với ảnh hưởng của workload cạnh tranh, nhưng đo before/after với nhiều dịch vụ cùng stop không xác định được nguyên nhân gốc duy nhất.

| Vòng (UTC) | User ms | Product ms | Order ms | Context ms |
|---|---:|---:|---:|---:|
| 12:50:24 | 579,132 | 253,573 | 274,957 | 297,909 |
| 12:50:35 | 17,265 | 13,123 | 11,817 | 13,999 |
| 12:50:45 | 21,407 | 18,620 | 22,621 | 17,144 |
| 12:50:55 | 19,028 | 14,151 | 15,398 | 9,637 |
| 12:51:05 | 36,798 | 14,924 | 14,267 | 13,051 |
| 12:51:15 | 33,121 | 12,474 | 12,488 | 16,491 |
| 12:51:25 | 14,865 | 25,588 | 13,273 | 24,325 |
| 12:51:36 | 13,841 | 11,683 | 12,841 | 24,906 |
| 12:51:46 | 11,392 | 11,754 | 16,791 | 11,852 |
| 12:51:56 | 17,503 | 27,128 | 19,374 | 18,160 |

Bốn approval gốc còn hạn 15:41:07 UTC, scope và governance hash đúng, ledger chưa consume trước lượt này. Không phát hành approval mới. Không chạy lại Normal A.

Processing A ghi User và Product 200 trước order_processing_failed rồi Order 500. Vị trí trước INSERT dựa trên hook, bundle không có DB transaction log. Timeout A ghi dependency_timeout và Order 504. Product 200 xuất hiện sau log Order completion 258,066 ms; Product SERVER span đóng sau Order SERVER span 268,150 ms. Collector kiểm closed span trước seal và giữ đúng deadline 2,0 s và delay 2,25 s.

Database A ghi 503 database_unavailable và log lỗi kết nối request DSN trong khi Order DB healthy. Sau rollback, Order /ready kiểm DB baseline và trả 200. Cascade A ghi Product 503, Order 502 dependency_unavailable và span liên kết qua Order client. Cơ chế dependency unavailable, handling propagated. Cả sáu container tạm dừng đã docker start thành công, exit 0.

Hậu kiểm sau khôi phục xác nhận cả sáu container Up. Kibana và n8n đang health starting lúc đầu. ES, Filebeat và PostgreSQL healthy. Host /ready User/Product/Order/Context lần lượt 200 sau 1,289/2,124/1,132/0,512 giây. Fault flags và accounting scope trống, không có rollback marker.

Regression sau khi chuỗi kết thúc và container đã khôi phục đạt 131 PASS, 0 FAIL trong 56,10 giây trên PostgreSQL cô lập, với ba cảnh báo deprecation. PostgreSQL test đã dừng. Không có OpenAI call hoặc bước thu blind cohort.
