# Gated fault adapters 7A.6C

| Cấu hình | Runtime và hợp đồng | Evidence bắt buộc |
|---|---|---|
| Normal A | Fault tắt, Order 201 | User/Product 200, Order root |
| Processing A | Order processing hook, 500 order_processing_error | Hai dependency 200 trước processing failure |
| Timeout A | Order 2,0 s, Product base 2,0 s cộng 0,25 s, Order 504 dependency_timeout | Caller timeout và Product 200 đến sau Order completion, Product SERVER span đóng |
| Database A | Fault database trên Order, 503 database_unavailable | DB container healthy độc lập, User/Product 200, Order repository connection failure |
| Cascade A | Product unavailable, Product 503, Order 502 dependency_unavailable | Liên kết Product server ↔ Order client ↔ Order root và log propagation |

Tái dùng SETUPS, fault hooks và producer receipts. compose.timeout-a.yaml chỉ áp dụng lúc activation. Timeout collector poll Docker theo trace và chỉ seal sau late Product completion cùng closed span. Reconcile ES và recheck receipt ở snapshot sau cutoff +420 giây. Chênh event làm batch fail closed. Deadline vượt giữ partial artifacts hiện có và đi cleanup. Database fault dùng request DSN hỏng trong repository, giữ startup DSN/DB container và không sửa dữ liệu PostgreSQL. Rollback gỡ overlay, kiểm app readiness với DSN baseline. Cascade root mechanism dependency_unavailable, handling propagated.

collect_benchmark_7a6c.py dùng chung run(), một business_post(), ràng buộc one-time approval ngay trước activation và POST. collection_runtime_lock dùng exclusive create để tuần tự hóa activation. Nếu rollback/postflight lỗi hoặc process bị dừng, marker được giữ, chặn lượt sau. Operator phải xác minh stack sạch và lưu audit recovery trước khi xử lý marker. Approval đã consume vẫn không tái sử dụng. Không fallback legacy.

Bundle giữ schemas preflight, activation, request_attempt, http_response, accounting, reconciliation, telemetry, hai context, snapshot_manifest, postflight, labels/dossier và bundle_sha256. activation_readback lưu runtime trước dispatch. Context chỉ evidence. Dossier NEEDS_REVIEW / UNVERIFIED, classification DEVELOPMENT_ACCEPTANCE và blind_eligible=false. Không nâng TRACE_COMPLETE.
