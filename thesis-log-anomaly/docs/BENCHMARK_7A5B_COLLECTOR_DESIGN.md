# Collector giới hạn 7A.5B

CLI yêu cầu đúng một slot và mặc định DRY_RUN. Dry-run không mở adapter, không tạo output và không gửi request. Đường thực thi chỉ dành cho adapter fixture được tiêm từ test. Mỗi campaign tối đa 2 POST mục tiêu, 0 POST setup và 420 giây work, cộng cửa sổ rollback/postflight riêng tối đa 30 giây. Timeout dựa trên hủy tác vụ async; adapter phải cancellable và không có POST ẩn. Không tự lặp POST lỗi, hoặc chuyển campaign.

Preflight → activation readback → POST một lần → capture → validate. Mọi lỗi dừng vòng lặp. Rollback được gọi nếu activation đã bắt đầu, kể cả khi bước này thất bại. Postflight chạy khi rollback được xác minh. Lỗi cleanup được ghi riêng, giữ fixture bundle đã thu hợp lệ và trạng thái thất bại. Output mới chứa cặp snapshot, telemetry, dossier NEEDS_REVIEW trong labels và SHA-256. Output fixture luôn engineering_fixture, không đủ điều kiện blind.

Validator dùng schema Context và kiểm tra Single đúng projection Order trong Cross, event ID, trace/event uniqueness trong campaign, ground-truth isolation, bộ event và payload digest giữa producer, Docker và Elasticsearch, cùng tính nhất quán bounded completeness. Adapter fixture cung cấp dữ liệu mô phỏng tại các boundary. Để mở live còn cần adapter ràng buộc preflight/resource, activation evidence, SOURCE seal và receipt có provenance thật, các collector Docker/ES hiện có, deadline subprocess và kiểm tra overlap campaign lịch sử. Collector 7A.4 giữ nguyên để không thay đổi hành vi của chiến dịch cũ.

Protocol 7A.5A giữ nguyên primary, Single = Order, Cross cùng trace, reviewer approval, exclusion rules và khóa nhãn riêng. Các nhóm lịch sử/development/smoke không được chọn hồi tố. Không sử dụng dự đoán LLM để chọn trace.
