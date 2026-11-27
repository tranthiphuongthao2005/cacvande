# Taxonomy v2 dự thảo

Chiều cơ chế có bốn họ lỗi xác định, một nhóm Normal và một nhóm Other/unknown. Chiều handling có bốn giá trị, hỗ trợ nhiều thuộc tính khi có bằng chứng riêng cho mỗi thuộc tính. Unknown dùng khi thiếu bằng chứng về handling. Normal dùng danh sách handling rỗng.

| Nhãn cũ | Cơ chế dự kiến | Handling có thể quan sát |
|---|---|---|
| Normal | Normal / no fault | Không áp dụng |
| Service Unavailable | Dependency unavailable | Local nếu lỗi quan sát trực tiếp, Propagated nếu lan sang caller |
| Cascade | Dependency unavailable trong mẫu hiện tại | Propagated |
| Retry Exhaustion | Dependency unavailable trong mẫu hiện tại | Retry exhausted, thêm Propagated nếu caller chịu hậu quả |
| Timeout | Dependency timeout | Propagated trong mẫu qua Order, Unknown nếu chưa xác định chuỗi |
| Database Failure | Database connection failure | Local tại Order trong các mẫu hiện tại |
| Processing Failure | Processing failure | Local tại Order trong các mẫu hiện tại |

Fault injection là thao tác hoặc cấu hình lab. Observed failure là hành vi quan sát như kết nối thất bại. Root cause là giải thích nguyên nhân có phạm vi và evidence. Propagation là ảnh hưởng qua ranh giới service. HTTP status là triệu chứng. Ví dụ 502 ở Order không xác định được vì sao dependency thất bại. Retry exhausted cần policy, số attempt, lỗi có thể retry và final outcome. Một attempt nghe tên log exhausted vẫn không đủ để kết luận có retry. Đối chiếu event và span theo trace trước khi gắn nhiều thuộc tính. Mapping chỉ dùng để duyệt thiết kế, giữ nguyên nhãn lịch sử.
