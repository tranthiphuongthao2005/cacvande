# Reference labels 7A.8R

10/10 nhãn có provenance hợp lệ và trạng thái DERIVED_UNVERIFIED. 0 contradiction qua kiểm tra kỹ thuật. reference_labels.json giữ case ID, candidate mechanism/service/handling, nơi quan sát lỗi, event IDs, source path/hash và giới hạn. Tệp nằm ngoài inference input.

| Cấu hình | Nhãn ứng viên và evidence |
|---|---|
| Normal | Không fault, healthy User/Product, Order 201 |
| Processing | Order processing failure sau hai lookup 200, hook trước INSERT. Không có transaction audit riêng |
| Timeout | Delay phía Product, Order quan sát 504; Product completion muộn và closed SERVER span |
| Database | Request DSN connection failure ở Order, 503 database_unavailable và PostgreSQL healthy |
| Cascade | Product unavailable, Product 503, Order 502 với span/log liên kết, handling propagated |

Kiểm runtime activation, status/error và span chain. Nhãn chính bám vào fault injection và evidence trong phạm vi lab. Mâu thuẫn nếu có sẽ giữ UNRESOLVED trong audit. Chưa có phê duyệt reviewer.
