# Thiết kế truy xuất log cho DetectionSession

Giai đoạn này chốt interface đọc log, chưa xây Detection API. app/contracts.py giữ contract hiện có.

1. Truy vấn exact term trace_id trên thesis-logs-* và giới hạn thời gian/cỡ dữ liệu. Với trace nhiều trang, dùng PIT và search_after theo @timestamp, event_id để tạo snapshot ổn định.
2. Xác minh trace ID và dedup theo event_id. Dùng _source.app cho provenance. Map @timestamp hoặc app.timestamp, service_name, event_id, span_id, level, message và status_code vào danh sách events. Không đưa body, credential, ground truth hoặc nhãn fault vào contract.
3. Thứ tự ổn định là timestamp UTC rồi event_id. Tie-break giúp tái lập; UUID không biểu diễn thứ tự nhân quả. Dùng parent/link của span nếu có hệ thống lưu traces và chỉ sắp theo thứ tự tô-pô khi quan hệ đủ rõ. Bản index hiện chỉ lưu log app.
4. service_name cấp session ưu tiên service gốc từ root SERVER span đã xác minh hoặc metadata của ingress. Khi chỉ có log, Order là ứng viên nếu trace có request Order, nhưng không suy diễn root bằng bản ghi request_completed xuất hiện đầu tiên. Với nhiều gốc hoặc bằng chứng thiếu, đánh dấu partial và dùng giá trị unknown theo contract cho tới khi xác minh.
5. Thu thập tới khi trace qua watermark hoặc timeout. Nếu thiếu span, mất event, cắt ngưỡng 2.048 hoặc không thấy kết thúc request, đặt source_metadata.completeness=partial, theo dõi dropped_events khi biết. Tránh gộp các trace khác nhau khi thiếu trace_id.
6. session_id ổn định theo environment, trace_id và phiên bản sessionization. Giữ tên service trên từng event để phân biệt report của User, Product và Order. Ground truth chỉ join offline qua trace_id để đánh giá sau này.
7. Trước Detection API, khóa chính sách window và dài/ngắn, vocabulary, OOV, template, support provenance và checkpoint tương thích. Đo domain shift và false positives trên trace microservices trước khi đưa score vào workflow.
