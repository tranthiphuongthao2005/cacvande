# Kiểm chứng giai đoạn 1

- pytest 14/14, gồm Unit/API, hợp đồng session, PostgreSQL integration qua socket thật, W3C parent–child và bảy fault scenario. Native integration dùng PostgreSQL 16 tạm với ba database, đã dừng sau suite. Một cảnh báo deprecation từ Starlette TestClient đối với alias AnyIO.
- Docker Compose config hợp lệ. Đã build ba image, khởi động ba service và ba PostgreSQL container, kiểm tra cả ba /ready.
- Tạo User, Product và Order trên stack Compose. Order trả HTTP 201. Trace 9dbd3eb8b7cf8a349a627c1d7fb1a3b4 xuất hiện trong JSON logs của cả ba service cùng 5 spans. Native integration test xác minh quan hệ cha–con của năm span.
- Tất cả bảy scenario đã chạy trên Compose. Có ít nhất một ground-truth record và một snapshot telemetry riêng cho mỗi scenario. Ground truth được join ngoại tuyến qua trace_id.

| Scenario | HTTP quan sát |
|---|---:|
| normal | 201 |
| timeout | 504 |
| unavailable | 503 |
| database | 503 |
| processing | 500 |
| retry | 502 |
| cascade | 502 |

Bài retry xác nhận ba lần gọi Product. Cascade xác nhận User trả 200, Product trả 503 và Order trả 502 dưới cùng trace.

Kiểm tra nguồn nghiên cứu xác nhận 63 file khớp fingerprint, gồm chín file Python gốc, checkpoint baseline, dữ liệu NPZ được bảo vệ, scorer và kết quả đã khóa. Frozen protocol có SHA-256 308e29ba2c48ff92c4ea3230206c99194daeb1e85a5832088c5b635c8285c63b. Check chỉ băm byte với artifact nhạy cảm, không đọc final labels hoặc nạp model.
