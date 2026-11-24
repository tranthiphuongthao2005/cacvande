# Kế hoạch quy mô benchmark

Đơn vị thu là trace ghép cặp; đơn vị độc lập cần chứng minh là nhóm campaign/configuration. Hai run cùng config đo lặp thực thi. Fault families hoặc workload gần nhau có thể bị gộp sau audit. Giữ một nhóm nguyên vẹn khi split. Giữ Single Order và chỉ đưa vào cặp chính trace có Order. Normal là negative control. Unavailable trực tiếp Product có thể nằm trong bảng coverage riêng hoặc thiết kế biến thể Order gọi dependency không khả dụng, nhưng không được lặp Cascade rồi tính là nhóm độc lập.

| Phương án dự trù | Phân bổ mục tiêu | Số cặp tối đa nếu đủ điều kiện | Lượt API tối đa trước lỗi/retry | Khối lượng review |
|---|---|---:|---:|---|
| Minimal feasibility | 7 strata vận hành × 2 nhóm cấu hình đề xuất × 2 trace mới | 28 | 56 | 56 output, 112 lượt chấm khi có hai người |
| Expanded thesis | 7 strata × 4 nhóm cấu hình đề xuất × 3 trace mới | 84 | 168 | 168 output, 336 lượt chấm trước adjudication |

Số trên là mức đặt lịch, chưa bảo đảm thu đủ nhóm hoặc đủ power. Ưu tiên Normal, Processing và các variant chưa có batch; bổ sung đủ các cơ chế khác dưới workload đa dạng, kiểm độ nhạy template, evidence và fault location. Không vượt batch đã được phép. Khi nhóm config bị gộp hoặc thiếu review, báo mẫu số thực. Feasibility đo tỷ lệ trace chấm được, độ bất đồng và độ phủ, thường chỉ báo descriptive. Expanded tăng cơ hội có nhóm độc lập cho bootstrap, nhưng vẫn phải khóa số nhóm tối thiểu và giả định trước khi đánh giá.

Độ chính xác ước lượng phụ thuộc biến thiên giữa nhóm và số cặp discordant. Với giả định nhóm độc lập và hiệu số chuẩn hóa trong [-1,1], công thức chuẩn xấp xỉ n = (1,96 × SD / half-width)^2. SD chưa biết; nếu SD=0,5 và half-width=0,20 thì xấp xỉ 25 nhóm, còn SD=1 cần khoảng 97. Chỉ dùng ví dụ để lập kế hoạch, vì ít nhóm, phụ thuộc, mất cặp và bootstrap có thể đổi đáng kể khoảng bất định. Không phân tích power hay significance dựa vào số trace danh nghĩa.

Chưa có ngân sách hoặc model snapshot thực. Ước chi phí sau khi có bảng giá khóa theo `(input_tokens × đơn giá input + output_tokens × đơn giá output) / 1.000.000` nếu đơn giá tính trên triệu token, cộng dự phòng lỗi được phép. Dùng một lượt đo chi phí được phê duyệt trước khi nâng quy mô. Không tự retry hàng loạt.
