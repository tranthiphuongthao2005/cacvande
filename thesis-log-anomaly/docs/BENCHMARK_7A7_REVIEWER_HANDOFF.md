# Reviewer handoff 7A.7

Chỉ bàn giao các packet từ run đã qua kiểm kỹ thuật. Reviewer packets đặt dưới reviewer_packets, snapshot inference dưới inference_snapshots theo trace và mode. labels/dossier.json, activation, telemetry và governance nằm ngoài export inference. Packet chứa candidate mechanism/service/handling, chứng cứ runtime, HTTP, snapshot hashes, rollback/receipt và event IDs. Normal dùng negative-case evidence thành công và fault scope tắt.

Reviewer đối chiếu proof trước khi dùng importer. Dossier giữ UNVERIFIED / NEEDS_REVIEW. Cần identity độc lập với người tạo/duyệt campaign, evidence refs và quyết định thật. Không ký thay, không đem kết quả LLM vào review. Việc audit phát hiện trùng run, trace hoặc event nội bộ và đối chiếu trace/run với development/acceptance. Kiểm near-duplicate các template/campaign còn thuộc bước review trước 7A.8.
