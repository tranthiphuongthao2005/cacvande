# Cross-service Context Retrieval

`context-service` là FastAPI process riêng. `app/context_store.py` dùng Elasticsearch snapshot; `app/incident_context.py` kiểm tra hình thức, tạo timeline và lập các quan hệ dependency có bằng chứng. `app/context_api.py` phục vụ HTTP. Store và schema giữ phạm vi context tách khỏi scoring.

Đối chiếu mapping thật xác nhận trace ID, event ID, span ID, request ID, service, dependency, error, endpoint và HTTP method là keyword. Thời gian dùng date_nanos, status dùng integer, message dùng text. ES lưu log ứng dụng với mã sự kiện, còn dữ liệu parent span nằm ngoài index này. `_source` được giới hạn vào trường công khai cần đọc; projection bảo vệ cả khi index có field bổ sung. Chỉ trả tên message và mã lỗi có trong hợp đồng.

Query dùng exact term trace ID trên `thesis-logs-*`, với cửa sổ tối đa tám ngày để bao phủ retention bảy ngày. Mode single thêm exact term service ngay trong ES. Mỗi snapshot dùng PIT, `search_after` theo timestamp, event ID và shard doc; đóng PIT khi kết thúc. Đọc tối đa 513 hit để chỉ trả tối đa 512 raw document và phát hiện truncation. Tie-break phục vụ tái lập thứ tự, còn quan hệ nhân quả cần bằng chứng khác. [Elasticsearch 8.19 về PIT và phân trang](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/paginate-search-results.html)

Container chạy UID 10001, filesystem chỉ đọc, 192 MiB, 0,5 CPU và host bind 127.0.0.1:8015. Key riêng 30 ngày chỉ đọc index lab. Bootstrap key dùng tài khoản quản trị ở host; tài khoản đó không được chuyển vào service. Overlay không gắn Docker socket, dữ liệu nghiên cứu hoặc PostgreSQL volume. Key local nằm ngoài source và build context. Transport dùng mạng logging hiện có.
