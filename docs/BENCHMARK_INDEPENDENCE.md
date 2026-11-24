# Độc lập và leakage

**Known-fault generalization** là mục tiêu ưu tiên. Fault family có thể xuất hiện trong development nhưng evaluation phải là các cấu hình và campaign riêng, với nguồn evidence độc lập và trace chưa từng xem. **Unseen-fault generalization** giữ toàn bộ cơ chế evaluation ngoài development, chấm và báo cáo riêng. Thay ID, thời gian hoặc body riêng lẻ không tạo cơ chế mới.

| Cấp | Tiêu chí |
|---|---|
| Execution riêng | Request thực, run ID và trace ID khác nhau, event ID không chia sẻ |
| Configuration khác | Fingerprint setup và workload khác nhau. Đây chỉ là tín hiệu chẩn đoán; cần xem thành phần cấu hình có ý nghĩa về hành vi để xác nhận độc lập |
| Mechanism khác | Cơ chế gốc khác có evidence bên hệ thống, ví dụ timeout chủ động và Postgres không kết nối; số retries khác cùng Product 503 vẫn có thể chung cơ chế |

Tool hợp nhất cùng campaign, chữ ký template đã gộp lặp, tập template trùng hoặc cùng fault config và workload family. Kiểm tra exact observable log duplicates sau chuẩn hóa service/message/status và so chữ ký với audit 7A. Báo Jaccard cho các cặp template, cùng cờ trùng config, workload family và campaign. Jaccard hỗ trợ review, không tự xác nhận độc lập. Không suy đều request payload giữa 7A và 7A.1 vì 7A không giữ payload. Workload hash hiện gồm quantity, thứ tự tạo fixture, khoảng nghỉ, entry service và concurrency, không phải digest raw request.

Group-aware split giữ mỗi cụm nguyên vẹn. Validator kiểm assignment có cả development và evaluation, không cắt cụm, reject trace đã xem hoặc trùng lịch sử, run không VALID hay thiếu annotation VERIFIED. Known yêu cầu family evaluation đã có trong development; unseen yêu cầu cơ chế evaluation vắng khỏi development. CLI hỗ trợ kiểm đề xuất bằng `--validate run_manifest.json --split assignment.json --target known`. Chỉ curator khóa khi đã kiểm tra coverage, near-duplicate chưa được phát hiện, độc lập theo cơ chế và có phê duyệt người vận hành. Không dùng score để chia tập.

Pilot này có bốn request riêng và hai fault configurations, gồm base không lỗi và Product unavailable gây cascade. Bốn workload hash khác nhau nhưng chỉ có một workload family và một campaign. Cả bốn thuộc **một nhóm phụ thuộc**. Một cơ chế lỗi đã quan sát, hai profile nếu tính cả Normal. Không có configuration độc lập được xác minh. Thống kê chính thức phải lấy execution/configuration group phù hợp làm đơn vị resampling, không dùng bốn trace làm bốn nhóm.
