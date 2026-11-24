# Readiness 7A.5C

Normal A có evidence live trong một integration smoke. Độc lập cấu hình chưa được xác minh. Không chuyển smoke vào blind set, không sửa matrix 7A.5B để tái phân loại dữ liệu lịch sử và không khóa cohort. Không chạy fault campaign, OpenAI, HDFS final hay Detection scoring.

Trước bước cohort cần quyết định taxonomy Service Unavailable/Cascade/Retry, duyệt cấu hình độc lập và budget, làm rõ chiến lược khi handoff UNCONFIRMED, xác minh 7 dossier đang NEEDS_REVIEW và khóa cohort/protocol nếu operator cho phép. Hiện 0 ground truth VERIFIED và 0 blind-eligible.
