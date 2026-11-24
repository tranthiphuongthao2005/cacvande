# Kiến trúc LLM Analysis Service

Người vận hành cung cấp trace đã biết hoặc chọn từ một lượt scenario. LLM Service đọc Context Service theo trace và scope, validate và chiếu dữ liệu qua allowlist, gọi provider, xác minh structured output rồi lưu báo cáo. Backend không có kết nối Detection, Elasticsearch hoặc hệ thống thực thi remediation. Không dùng các file nhãn kịch bản trong runtime.

Service FastAPI riêng bind 127.0.0.1:8016, UID 10001, filesystem chỉ đọc, 192 MiB và 0,5 CPU. Context được gọi bằng tên service trong mạng Compose. Chế độ mock trả báo cáo có thể kiểm chứng từ JSON, với model ID riêng và không tốn API.

Provider chính dùng Python SDK chính thức 2.8.1, Responses API với `responses.parse`, schema strict, `store=False` và không cấu hình tools. Địa chỉ API được cố định. Provider chỉ được khởi tạo khi có key, model và cờ cho phép gửi dữ liệu lab. Readiness báo cấu hình đã sẵn sàng theo local và ngân sách còn. Kiểm tra readiness không phát sinh truy vấn provider. [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) · [SDK 2.8.1](https://github.com/openai/openai-python/releases/tag/v2.8.1)

Hai phân tích đồng thời mỗi process. Context timeout 6 giây, provider timeout 20 giây mỗi lần gọi, SDK retry bằng 0. Mặc định cho một lần gọi ngoài mỗi process và không retry output. Khi cho phép một retry validation, mỗi lần thử dùng thêm một đơn vị ngân sách. Bộ đếm reset khi khởi động lại, nên chỉ là giới hạn lab theo process. Giới hạn 1.200 output token mỗi lần gọi. Kết quả có tối đa 128 báo cáo gần nhất lưu trong RAM.
