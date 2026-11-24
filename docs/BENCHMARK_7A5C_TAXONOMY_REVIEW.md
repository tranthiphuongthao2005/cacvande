# Rà soát taxonomy 7A.5C

Ghi hai chiều cho mỗi trường hợp. Cơ chế mô tả sự kiện gây lỗi. Hành vi mô tả cách lỗi xuất hiện ở caller hoặc hết ngân sách retry. Với Retry exhausted, ghi thêm propagated_to nếu caller trả lỗi để không mất thông tin propagation.

| Nhãn hiện tại | Cơ chế gốc đề xuất | Hành vi đề xuất | Bằng chứng phân biệt |
|---|---|---|---|
| Normal | Không có lỗi quan sát trong phạm vi | Không áp dụng | Fault flags tắt, các dependency thành công, Order 201 |
| Service Unavailable | Dependency unavailable | Local nếu quan sát trực tiếp. Propagated nếu có cạnh sang Order | Service 503 hoặc lỗi kết nối, caller và span liên kết nếu có |
| Cascade | Dependency unavailable trong các mẫu Product/User hiện tại | Propagated | Span/log bên phát sinh và hậu quả trên caller |
| Retry Exhaustion | Dependency unavailable với 503 hoặc transport trong các mẫu hiện tại | Retry exhausted | Policy, timestamp, attempt count, lỗi retryable kéo dài và final outcome |
| Timeout | Dependency timeout | Local, Propagated hoặc Retry exhausted tùy bằng chứng | Deadline, caller timeout và thời điểm phản hồi dependency |
| Database Failure | Database connection failure | Local tại Order trong mẫu hiện tại | Repository connection failure và health DB độc lập |
| Processing Failure | Processing failure | Local tại Order trong mẫu hiện tại | Stage và nhánh xử lý, không INSERT |

Nếu không đủ bằng chứng xác định chuỗi, ghi Unknown ở chiều hành vi. Cascade là mô tả lan truyền trong dữ liệu hiện có. Retry Exhaustion là kết quả giao thức xử lý lỗi. HTTP 502 có thể xuất hiện trong cả hai và không đủ để phân biệt. Service Unavailable trực tiếp thiếu Order nên không thể ghép cặp theo protocol. Unavailable qua Order → Product 503 → Order 502 chồng lấn Cascade A. Có thể giữ 7 strata vận hành với grouping quan hệ, hoặc phân tầng theo cơ chế × hành vi và lập lại kế hoạch mẫu. Mọi thay đổi số nhóm hoặc taxonomy chính thức cần operator phê duyệt và protocol draft mới.
