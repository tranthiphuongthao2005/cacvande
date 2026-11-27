# Chất lượng pilot 7A.1

| Biến thể | Run hợp lệ | HTTP | Event | Docker ↔ ES | Cross completeness |
|---|---:|---:|---:|---|---|
| Normal | 2/2 | 201 | 6 | Khớp từng field | 2 PARTIAL |
| Cascade | 2/2 | 502 | 10 | Khớp từng field | 2 PARTIAL |
| Tổng | 4/4 | | 16 | 4/4 trace đối chiếu | 4 PARTIAL |

Có bốn trace ID và 16 event ID duy nhất. Tất cả event khớp giữa Docker và dữ liệu ES qua Context đối với ID, timestamp, service, span, level, message, status, dependency và mã lỗi. Mỗi trace có một root SERVER span đã kết thúc, bốn parent link tìm thấy trong stdout Docker và 0 event thiếu span tương ứng. Không có watermark chứng minh cả trace đã ingested, nên không đổi completeness sang COMPLETE. Tỷ lệ đối chiếu telemetry là 4/4, tỷ lệ COMPLETE là 0/4.

Cascade cần User 200, Product 503, Order 502 và event Order báo Product dependency attempt failed. Chỉ HTTP 502 không đủ xác nhận behavior. Behavior check đạt cả bốn. Bốn sidecar label vẫn UNVERIFIED vì chưa có reviewer độc lập xác nhận nguyên nhân và chuỗi nhân quả. Trường root cause để null. Ground truth nằm riêng ngoài snapshots, logs, Context và inference.

Snapshot có bốn cặp Single Order/Cross. Single giữ tổng 8 event Order và cả bốn ở trạng thái UNKNOWN theo phạm vi một service. Validator xác minh nội dung từng event của Single đúng phân vùng từ Cross. Snapshot giữ completeness, warnings, event IDs và SHA-256. Có hai cụm exact signature trên bốn run (mỗi cụm hai) và cả bốn có signature trùng lịch sử. Audit tìm thấy không có ID trùng trong pilot; tương tự nội dung vẫn chặn việc đưa vào blind set.

[Quality audit CSV](../experiments/benchmark_7a1_pilot_seed124/quality_audit.csv) · [Snapshot manifest](../experiments/benchmark_7a1_pilot_seed124/snapshot_manifest.json) · [So sánh từng cặp](../experiments/benchmark_7a1_pairwise_similarity.json)
