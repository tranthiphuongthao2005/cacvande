# Thiết kế benchmark LLM độc lập

Mục tiêu là đánh giá phân tích sự cố theo trace đã biết. Hai mode chia sẻ tập trace và dùng cùng model snapshot, prompt version, schema, decoding, budget, rubric. Single chọn **Order** theo quy tắc đã định trước, chỉ bao gồm trace có Order để so sánh chính. Báo số trace ngoài phạm vi, gồm biến thể chỉ làm request Product trực tiếp. Cross dùng toàn bộ context của trace, chỉ dùng quan hệ dependency có log hoặc span chứng minh. Hai mode lưu danh sách event ID thực tế đã đưa vào provider và ID bị cắt nếu có.

| Kịch bản | Biến thể thu thập hợp lệ |
|---|---|
| Normal | Create Order và luồng đọc/cập nhật có dependency hợp lệ, thay workload, tần số và lượng request theo hành vi nghiệp vụ. |
| Timeout | Tạo delay ở User hoặc Product trước lookup, thay thời điểm vượt ngưỡng và có/không phục hồi. |
| Service unavailable | Chọn dependency thật theo luồng gọi, phân biệt 503 và kết nối không mở, giữ caller Order trong tập so sánh chính. |
| Database failure | Lỗi kết nối hoặc deadline Postgres tại User, Product hoặc Order, ghi đường lan truyền và vùng lỗi. |
| Processing failure | Lỗi nghiệp vụ tại các bước khác nhau, phân biệt lỗi validation hợp lệ và lỗi hệ thống. |
| Retry exhaustion | Thay số attempt theo cấu hình lab, lỗi liên tục hoặc gián đoạn. Chỉ xếp exhaustion khi budget thực sự hết. |
| Cascading failure | Biến thể User hoặc Product lỗi upstream, quan sát caller và có thêm tải chéo khi phù hợp. |

Các biến thể cần workload chạy lại trên topology/cấu hình độc lập, nhiều thời điểm và campaign. Giữ campaign, cùng cơ chế lỗi và các signature gần trùng trong một nhóm trước khi chia. Biến động giá, UUID, timing nhỏ hoặc đổi verbosity một mình chưa đủ tạo độc lập. Khi thay verbosity, dùng chính sách đã định cho cả Normal và Anomaly; không thêm log tiết lộ injection. Thu cấu hình và evidence offline, ghi digest của payload đã chuẩn hóa an toàn và bucket thời gian thay vì body thô. Lập bản đồ session, request, span, event IDs có provenance.

Kế hoạch khởi điểm gồm 14–28 trace mới cho dry-run nghiệp vụ và công sức annotation, rồi dự trù 42–84 trace cho đợt benchmark đầu với nhiều nhóm độc lập trên mỗi family. Đây là mức lập kế hoạch, chưa chứng minh power. Hai mode tương ứng 84–168 lượt gọi nếu tất cả được giữ, chưa tính lỗi và mọi retry phải được phê duyệt riêng. Chốt quy mô sau dry-run dựa trên số nhóm thực, tỷ lệ thiếu dữ liệu, chi phí model và công sức hai reviewer. Đợt dry-run và toàn bộ trace hiện có nằm ngoài blind evaluation. Chưa thực hiện thu mới trong 7A.

Trước bất kỳ lượt evaluation nào, curator khóa group assignment, danh sách trace, context snapshots, label sidecars, rubrics, model snapshot, prompt, decoding, input budget, schema, bootstrap seed và quy tắc công bố. Chỉ thu thêm khi thiếu độc lập hoặc evidence, không thay split dựa trên score.
