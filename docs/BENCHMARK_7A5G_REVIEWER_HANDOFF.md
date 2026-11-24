# Processing A — hồ sơ bàn giao reviewer

Chỉ cấp hồ sơ này cho reviewer ground truth. Run 77423da550654d5497ac8cc2a8d1ec41, trace 743b36700c9da51381cdb1889103ba69. Candidate từ collector là processing_failure tại Order, sau User/Product lookup và trước repository.create theo hook. Trạng thái dossier giữ UNVERIFIED / NEEDS_REVIEW. Đây là DEVELOPMENT_PILOT, blind_eligible=false.

Bundle gốc nằm ở ../experiments/benchmark_7a5/processing_a_development_pilot/. Dùng bundle_sha256.json để xác minh các file sau trước khi xem xét.

| Evidence | File và nội dung |
|---|---|
| Activation | activation.json, request_attempt.json, preflight.json. Order processing; Product fault rỗng; User không bật lab fault |
| HTTP | http_response.json và activation.json. HTTP 500, order_processing_error, 797 ms |
| Span và event | telemetry.json. User 200 event 17effc7807c24a639bc308678dfee27b, Product 200 event 47db8d4362b54748a078d94370ea1175, processing log 3d2ea9750f3047ed8ef6d7e8fe3c5e6e, Order 500 event 82cd05e3c1c44db7bb2abcbef319ae6c |
| Capture | accounting.json, reconciliation.json, receipts/743b36700c9da51381cdb1889103ba69.json. 4/4/4, bounded capture |
| Snapshot | snapshot_manifest.json và hai context-*.json, chứng minh projection |
| Rollback | postflight.json. PASS, bốn readiness 200, không còn fault/scope |
| Dossier | labels/dossier.json. SHA-256 b116891edacb675bed2da1fedcda8ae6ea66e19fbb7fe331f7dd15d0851cb60a |

Reviewer đánh giá vị trí hook, chuỗi span và symptom. Giữ giới hạn về chứng từ DB, raw Docker replay, handoff, cutoff và phạm vi quan sát. Có thể accept, reject, inconclusive hoặc yêu cầu thêm evidence theo HUMAN_REVIEW_WORKFLOW.md. Dossier pilot hiện dùng references phẳng và thiếu supporting_evidence.event_ids mà importer hiện yêu cầu. Operator cần duyệt một bản review dossier tương thích, có digest và provenance trỏ về bản gốc, trước khi nhập quyết định. Không chỉnh dossier gốc hay cấp chữ ký ở 7A.5G.
