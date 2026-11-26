# Cổng quyết định 7A.5E

operator_approval_template.json là mẫu PENDING cho taxonomy v2, rubric, primary outcome, abstention, completeness, cohort ceiling, grouping, reviewer assignment và provider budget. Protocol và taxonomy giữ DRAFT. Quyết định phương pháp tách khỏi quyền chạy một pilot. Không có chữ ký hay quyết định nào được tạo trong giai đoạn này.

Pilot cần file phê duyệt riêng do operator quản lý, với status APPROVED, operator định danh, campaign processing-a-development-pilot, configuration processing-a, maximum_business_posts đúng 1, output path tương đối từ root project, scope Order/processing và rollback plan khớp mẫu. Dùng output mới trong experiments/benchmark_7a5. File này là bản ghi operator tin cậy, validator kiểm phạm vi và lưu SHA-256 khi preflight qua. Chưa tích hợp xác thực chữ ký mật mã cho operator. Không dùng mẫu PENDING hoặc flag --live đơn lẻ để chạy. Approval pilot không mở cohort hay provider.
