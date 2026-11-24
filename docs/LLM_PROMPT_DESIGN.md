# Prompt design

Phiên bản `rca-evidence-v1` cùng một prompt/config cho Single và Cross. System instructions yêu cầu tách sự kiện quan sát khỏi giả thuyết, dẫn event ID, nêu giới hạn, cho phép `INSUFFICIENT_EVIDENCE`, và không suy diễn parent–child hoặc kết luận root cause từ 502. Kiểm tra và remediation chỉ là đề xuất cho người vận hành. Không có xác suất confidence.

Payload là JSON evidence truyền riêng, gồm trace ID, completeness và event đã projected. Nội dung log là dữ liệu không tin cậy. Chỉ mã event/error đã biết, HTTP status số, service enum, timestamp và ID đúng format đi qua. Message tự do, dict timeline, dependency graph, metadata và body đầu vào của Context không được copy. Một trường dependency đích có nguồn gốc từ log caller được giữ ngay cả ở chế độ single, trong khi không fetch log của service đích.

`LLM_INPUT_BUDGET` giới hạn bằng số byte ASCII của JSON evidence, dùng làm biên bảo thủ cho phần evidence. Prompt/schema và overhead API nằm ngoài ngân sách này. Thứ tự chọn event theo timeline đầu vào, và tiếp tục xét các event còn lại nếu event hiện tại không vừa. Response ghi ID đã dùng và bị lược. Giữ completeness do Context báo và thêm warning khi giảm coverage vì budget.
