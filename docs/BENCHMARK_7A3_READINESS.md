# Readiness 7A.3

| Hạng mục | Kết quả |
|---|---|
| Telemetry integration | Một trace Order smoke thật, HTTP 201, 3 event nguồn đối chiếu 3 event ES. Hai request tạo fixture nằm ngoài trace đo. |
| Source seal | Đã tạo seal quan sát thật, chưa xác minh coverage toàn nguồn hoặc exporter drain. |
| Ingestion receipt | Đã kiểm chứng ID/nội dung khớp tại thời điểm đọc. Chưa có producer ACK hoặc watermark authoritative. |
| Context | V2 trả provenance. Smoke Cross PARTIAL, Single UNKNOWN. 4 cặp cũ giữ nguyên status/event IDs, không cấp receipt hồi tố. |
| Human review | Import HMAC thử bằng fixture. 0 quyết định thật, 0 VERIFIED. Bốn hồ sơ 7A.2 vẫn NEEDS_REVIEW. |
| Benchmark | Chưa mở rộng collection chính thức. Smoke tách riêng; cohort và source watermark còn thiếu. |
| Blind evaluation | 0 trace đủ điều kiện. |

Tạo `app/telemetry_receipts.py`, `compose.receipts.yaml`, hai công cụ smoke/import, test và bốn tài liệu. Cập nhật Context API/Dockerfile và README. Không thay đổi nhãn, instrumentation producer, lịch sử hay scoring. Kiểm 33 checksum pilot, 9 checksum 7A.2, 4 checksum smoke và 63 fingerprint MeCoLog. Detection vẫn NOT_READY_FOR_SCORING. Không gọi OpenAI và không mở HDFS final.

Context container healthy trên Docker Compose. Regression **65/65 pytest** trong 49,77 giây, gồm năm bài 7A.3 và PostgreSQL lab riêng, với ba cảnh báo deprecation có sẵn. Fixture kiểm thiếu seal/receipt, event tới muộn, missing/duplicate ID, field mismatch, child graph, seal version, bundle bị sửa, phạm vi Cross/Single, review thiếu signature hoặc quyền, isolation và tương thích v1.

[Tái lập smoke](REAL_TELEMETRY_RECEIPTS.md) · [Khởi động Context v2](COMPLETENESS_INTEGRATION.md) · [Nhập review](HUMAN_REVIEW_WORKFLOW.md) · [Artifact tích hợp](../experiments/benchmark_7a3_integration_verification.json)
