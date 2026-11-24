# Chuẩn bị reviewer

Reviewer queue có 7 packet dạng chỉ mục, mỗi packet liên kết dossier và form gốc cùng activation, HTTP, log/span và các event ID. Trường null nghĩa là chưa có bản ghi, không suy ra evidence không tồn tại. 3 packet batch ưu tiên P1, 4 pilot P2 dùng chuẩn hóa cách chấm. Packet chỉ cấp cho người xác minh nhãn, không nạp vào context LLM. Tách người xác minh nhãn khỏi người chấm output khi có thể.

1. Đối chiếu cấu hình đã ghi với activation và sự kiện quan sát. HTTP 502/503/504 là symptom; xác định cạnh caller/callee và timeline trước khi xác nhận root cause.
2. Phân biệt timeout có deadline bị vượt với dependency trả lỗi hoặc mất kết nối. Với lỗi DB, kiểm tra request DSN và health của server trước khi suy luận server crash.
3. Với Normal, kiểm tra luồng lành mạnh và hành vi mong đợi, ghi bounded absence trong phạm vi quan sát. Nếu evidence thiếu hoặc mâu thuẫn chưa giải quyết, chọn INCONCLUSIVE. Chọn REJECTED khi có căn cứ bác bỏ nhãn ứng viên.
4. Ghi reviewer ID, run ID, timestamp có timezone, decision, justification, dossier digest và event IDs đã xem. Với VERIFIED cần ít nhất một event. Operator xác minh allowlist rồi dùng công cụ import vào output mới theo HUMAN_REVIEW_WORKFLOW.md.

Không có quyết định thật trong giai đoạn này. Các phiếu vẫn NEEDS_REVIEW.
