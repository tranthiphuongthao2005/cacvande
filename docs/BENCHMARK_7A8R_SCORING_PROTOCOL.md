# Scoring trước output 7A.8R

Primary là mean paired Cross−Single exact root-cause accuracy trên fault pairs có hai output hợp lệ ANALYZED và nhãn tham chiếu resolved. Exact cần mechanism và root service đúng cùng evidence hợp lệ. Partial khác exact, cả partial và incorrect tính 0 trên scorable pairs. Báo thêm exact / 8 fault planned cho từng mode, với mọi outcome ngoài CORRECT tính 0, kể cả abstention, provider failure, invalid, missing hoặc reference unresolved. Giữ đủ mẫu số và coverage, null khi mẫu số bằng 0.

Báo bảy outcome riêng gồm CORRECT, PARTIALLY_CORRECT, INCORRECT, ABSTAINED, INVALID_OUTPUT, PROVIDER_FAILURE và MISSING_RESULT. Phân rã cặp thành both correct, Cross only, Single only, both incorrect và non-scorable, mỗi nhóm cấu hình báo riêng. 8 fault executions không tạo 8 cấu hình độc lập.

Root mechanism/service/handling accuracy chia theo output ANALYZED chấm được với thành phần reference có sẵn. Evidence support và unsupported claims chia trên claim chấm được, kể cả claim thiếu citation nếu có thể chấm. Abstention trên response đúng schema. Normal false attribution trên Normal ANALYZED chấm được. Latency, input/output token và cost dùng các attempt có số đo và bảng giá, ghi riêng coverage. Không tuyên bố statistical significance. Kết quả lưu riêng và bất biến theo lượt chạy.
