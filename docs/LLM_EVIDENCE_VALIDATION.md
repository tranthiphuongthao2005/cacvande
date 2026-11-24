# Kiểm tra bằng chứng

Preflight xác minh scope, trace ID nhất quán, event ID duy nhất và đúng format, completeness enum, thứ tự timestamp và start/end. Client không được gửi log hay nhãn. Context ngoài schema bị từ chối. Event được chiếu qua allowlist trước khi gửi.

Postflight nạp ModelAnalysis theo schema strict. Với một observation, event ID và service phải khớp. HTTP status, event message và dependency failure phải khớp đúng trường quan sát. Hypothesis và suspected cause phải tham chiếu event đã qua kiểm tra; affected services phải có observation. Cause phải null trong trạng thái insufficient evidence. Báo cáo không được lưu nếu schema hoặc chứng cứ cấu trúc không hợp lệ.

Tham chiếu hợp lệ và khớp fact cấu trúc vẫn không xác nhận ý nghĩa của câu `supports_claim` hay quan hệ nhân quả của giả thuyết. Response đánh dấu cần người kiểm tra và nêu giới hạn completeness. Prompt injection fixture xác minh message tự do và metadata lạ không tới provider. Kiểm tra regex output là lớp phụ trợ và không thay thế duyệt nội dung.
