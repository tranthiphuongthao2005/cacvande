# Tích hợp live collector 7A.5C

CLI tools.collect_benchmark_7a5c dùng DRY_RUN mặc định, nhận duy nhất normal-a và --max-requests 1. Live cần --live, --operator-confirmed và đường dẫn output mới ngay dưới experiments/benchmark_7a5. Preflight kiểm Docker Compose, disk, Docker VM memory, ba API, Context, Elasticsearch, DB health, producer module/version, checksum và fault/scope đang bật. Live tái sử dụng tooling producer-accounting và Compose overlay, không build image mới, không tạo pipeline log mới. Kiểm tra lại accounting scope và fault flags trước POST.

Work deadline 420 giây, cleanup deadline riêng 30 giây; Docker subprocess và POST dùng timeout giới hạn theo deadline. Không tạo user/product mới. Collector GET một Order fixture có sẵn, sau đó POST Order duy nhất, không retry. Health checks và Context là request đọc riêng. Smoke đóng capture scope, dựng seal và receipt, kiểm producer/Docker/ES, hoàn nguyên Compose overlay và làm postflight. Nếu lỗi không tự chạy lại. Bundle đánh dấu INTEGRATION_SMOKE và blind_eligible=false.

Context API v2 cung cấp hai snapshot. Receipt của smoke nằm trong bundle, chưa đăng ký vào thư mục receipts của Context Service, vì vậy provenance phía API null. Collector áp dụng classifier receipts hiện có tại chỗ và lưu kết quả cùng snapshot digest. Không sửa Context Service hay nâng TRACE_COMPLETE.

Sau smoke đã siết điều kiện output bằng mkdir độc quyền từ đầu và kiểm deadline trước khi ghi attempt marker. Cặp thay đổi này được kiểm offline; không có lượt POST thứ hai.
