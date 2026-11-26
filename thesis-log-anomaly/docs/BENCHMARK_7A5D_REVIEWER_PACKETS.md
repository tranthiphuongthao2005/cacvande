# Reviewer packets 7A.5D

Manifest có 7 packet với path và SHA-256 của dossier, blank form và tài liệu hỗ trợ. Năm packet đủ để reviewer xem xét một kết luận có phạm vi gồm ba batch và hai pilot Normal. Hai pilot Product unavailable có config/label do collector lưu và HTTP 503 → 502, nhưng không tìm được activation readback độc lập trong run, telemetry hoặc collector receipt. Giữ MISSING_EVIDENCE. Thiếu ACK hoặc source seal được ghi riêng.

Batch 01 có supplement SYSTEM_PREPARED_NOT_REVIEWED. Runtime Product unavailable và ba event Product 503, Order dependency_attempt_failed, Order 502 cùng trace hỗ trợ nghi vấn dependency unavailable tại Product, propagated sang Order. Một attempt, chưa đủ căn cứ gắn retry exhausted. Supplement nằm trong manifest, dossier và phiếu gốc giữ nguyên.

Operator chỉ định reviewer độc lập và giới hạn truy cập theo run. Reviewer nhận packet qua khu vực riêng biệt với inference context. Reviewer kiểm provenance, nội dung, khoảng trống và justification. Accept ánh xạ VERIFIED, Reject ánh xạ REJECTED, Mark inconclusive ánh xạ INCONCLUSIVE. Request more evidence ghi ticket riêng và giữ NEEDS_REVIEW, vì importer hiện chưa có enum này.

Nhập quyết định bằng tools.import_review_7a3 theo HUMAN_REVIEW_WORKFLOW.md. Xác minh reviewer allowlist, signature HMAC, run ID, digest dossier và event references; giữ receipt ở đường dẫn riêng. Supplement chưa được importer gắn digest trong phiếu gốc. Nếu cần ký xác nhận trực tiếp supplement, operator phải phê duyệt dossier phiên bản mới có digest và giữ bản cũ làm audit. Ghi từng phiếu, disagreement và adjudication độc lập, lưu lý do và dấu thời gian. Reviewer xác minh nhãn nên khác người chấm output. Không gán chữ ký hoặc quyết định trong 7A.5D.
