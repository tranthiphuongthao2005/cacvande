# Processing A development pilot

Chọn processing-a đã FIXTURE_VERIFIED. Hợp đồng nằm ở experiments/ground_truth.json, app/api.py và fixture Order. Fault hook sau hai lookup User/Product thành công, trước repository.create. Order trả 500 với order_processing_error và log order_processing_failed. Mong đợi một Order SERVER root đã đóng, hai Order CLIENT span và hai dependency SERVER span. Không thêm fault hook hoặc sửa business logic.

Collector tái dùng Compose và producer accounting. Preflight kiểm DB/ES/Context, readiness ba service, tài nguyên, module và fault flags. Đọc Order fixture có sẵn, arm scope run/trace, bật cờ processing trên Order và đọc lại runtime cả ba service. Gửi đúng một POST. Capture Docker, accounting và ES; đối chiếu ID, nội dung, flush, handoff, seal, receipt. Rollback Compose baseline và kiểm postflight. Sau cutoff lấy Single Order và Cross cùng trace, kiểm Order projection, isolation, completeness và checksums. Dossier riêng mang candidate chưa review. Bundle là DEVELOPMENT_PILOT, blind_eligible=false. Thiếu handoff không được nâng TRACE_COMPLETE.

Không có bundle live hoặc trace Processing A sinh ra ở 7A.5E.
