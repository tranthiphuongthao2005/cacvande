# Kiểm chứng batch Cascade 7A.4

| Hạng mục | Quan sát |
|---|---|
| Campaign / run đo / technically valid | 1 / 1 / 1 |
| Activation | Product có fault unavailable; Order được cấu hình một attempt. Quan sát User 200, Product 503, caller failure và Order 502. |
| Producer / Docker / ES | 5 / 5 / 5 event, nội dung khớp |
| Lỗi telemetry | 0 thiếu, 0 unexpected, 0 trùng và 0 late trong kỳ quan sát |
| Flush và handoff | 5/5 event flush ở cả hai sink, Filebeat handoff UNCONFIRMED |
| Cặp snapshot | 1 cặp. Single Order 3 event UNKNOWN, Cross 5 event PARTIAL |
| Nhãn | 0 VERIFIED, 1 NEEDS_REVIEW |

Run ID `1d3140d225414983ac361d14ed978220`, trace `96a68fa080ebbc19e71aedcc5bc2fd48`. Thu đúng một GET tham chiếu và một request đo. Các probe readiness tách riêng. Không gọi OpenAI hay n8n.

Hậu kiểm lần đầu gặp kết nối bị ngắt khi container vừa rollback. Collector đã lưu evidence, sau đó finalize lại từ cùng bundle sau khi readiness ổn định. Không gửi lại request đo. Preflight ban đầu đã qua gate nhưng snapshot RAM lúc đó chưa được lưu; manifest ghi snapshot tài nguyên hậu kiểm và để duration gốc null. Tool đã được sửa để lưu preflight trước khi đo và đợi readiness sau rollback có giới hạn.

[Campaign manifest](../experiments/benchmark_7a4_batch01/campaign_manifest.json) · [Run manifest](../experiments/benchmark_7a4_batch01/run_manifest.json) · [Telemetry CSV](../experiments/benchmark_7a4_batch01/telemetry_audit.csv) · [Snapshots](../experiments/benchmark_7a4_batch01/snapshot_manifest.json) · [Dossier và phiếu](../experiments/benchmark_7a4_batch01/labels/) · [Checksum bundle](../experiments/benchmark_7a4_batch01/bundle_sha256.json)
