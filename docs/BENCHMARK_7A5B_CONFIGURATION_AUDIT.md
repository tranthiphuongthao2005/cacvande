# Kiểm toán cấu hình 7A.5B

| Slot | Nhóm | Trạng thái | Đường thực thi hoặc đề xuất | Evidence | Kiểm chứng |
|---|---|---|---|---|---|
| normal-a | normal | FIXTURE_VERIFIED | Order creates single-item order with faults disabled | 201 and persisted row | API + PostgreSQL regression |
| normal-b | normal | DESIGN_BLOCKED | Different healthy path requires genuine workload feature; order has one product_id | Healthy alternate dependency path | Inspect schema; no fixture claim |
| unavailable-a | unavailable | DESIGN_BLOCKED | Direct Product lacks Order; Order to Product 503 is same chain as cascade-a | Order SERVER, Product 503 and Order 502 reproduced as engineering evidence | Order MockTransport plus existing cascade PostgreSQL fixture |
| unavailable-b | unavailable | DESIGN_BLOCKED | Need separate taxonomy or causal topology from Cascade | Independent fault and propagation evidence | Operator review before protocol revision |
| processing-a | processing | FIXTURE_VERIFIED | Existing after dependency lookup before create | Order 500, no INSERT, upstream calls completed | API fault fixture and PostgreSQL regression |
| processing-b | processing | FIXTURE_VERIFIED | Lab-only hook after payload validation and before dependency lookup | Order 500, stage log, no lookup or INSERT | API MockTransport and memory repository |
| retry-a | retry | FIXTURE_VERIFIED | Product HTTP 503 through three attempts | Three ordered spans, HTTP 503, final dependency_unavailable | MockTransport plus PostgreSQL regression |
| retry-b | retry | FIXTURE_VERIFIED | Product ConnectError through three attempts; no Docker activation adapter | Three ordered attempt spans with no HTTP status and final dependency_unavailable | MockTransport only |
| cascade-a | cascade | FIXTURE_VERIFIED | Product 503 propagates to Order | Product 503 followed by Order 502 with dependency evidence | PostgreSQL regression |
| cascade-b | cascade | FIXTURE_VERIFIED | User GET 503 propagates to Order, no Product call | User 503 with Order SERVER and User CLIENT | PostgreSQL integration fixture |
| timeout-a | timeout | FIXTURE_VERIFIED | Product delay crosses caller deadline | Order 504 and Product attempt | PostgreSQL regression |
| timeout-b | timeout | FIXTURE_VERIFIED | User GET delay crosses caller deadline; no Product call | Order 504 and User attempt | PostgreSQL integration fixture |
| database-a | database | FIXTURE_VERIFIED | Order request DSN is unreachable while DB startup DSN works | Order 503, connection failure | PostgreSQL regression |
| database-b | database | DESIGN_BLOCKED | Requires isolated test role and SQLSTATE evidence; no lab hook added | Healthy reachable server and authentication failure | Future isolated DB fixture |

configuration_matrix.json ghi blocker và rủi ro từng slot. FIXTURE_VERIFIED bao gồm đường code có fixture; LIVE_VERIFIED đòi evidence từ campaign đã được duyệt. Chưa có căn cứ xác nhận tính độc lập cấu hình.

Order schema có một product_id; tăng quantity không tạo luồng xử lý nhiều sản phẩm. Normal dùng cấu hình không bật fault và kiểm tra đơn được lưu. Hook xử lý trước lookup phân biệt với hook sau lookup, đều chặn trước INSERT. Tắt hook để phục hồi. Timeout ở Product hoặc User là hai vị trí trên cùng cơ chế deadline. DB request DSN lỗi kết nối không chứng minh PostgreSQL crash.

Order SERVER span, Order log và dependency CLIENT span cho phép phân tích Product 503 qua Order. Với Product thực sự trả 503, có thêm Product SERVER/log; transport refusal có thể chỉ có bằng chứng phía caller. Chuỗi một attempt Product 503 → Order 502 vẫn trùng Cascade A, vì vậy đề xuất gộp hai nhánh Product unavailability thành một họ nguyên nhân, phân tầng theo phạm vi ảnh hưởng hoặc retry. Cần người vận hành duyệt trước khi đổi taxonomy. Policy retry hiện tại dùng attempts cố định, backoff 50 ms nhân attempt, retry 502/503/504 và httpx request errors, và trả trạng thái cuối. Dùng count, timestamp, status từng attempt và log dependency_exhausted để diễn giải. Khi attempts = 1, tên log exhausted chỉ cho thấy ngân sách kết thúc, không chứng minh đã retry.
