# Minimum viable cohort 7A.6B

| Họ | Đường cấu hình | Mục tiêu trace mới |
|---|---|---:|
| Normal | Normal A | 2 |
| Dependency timeout | Timeout A | 2 |
| Database connection failure | Database A | 2 |
| Processing failure | Processing A | 2 |
| Dependency unavailable | Cascade A như biến thể propagated | 2 |

Bốn họ fault có đường ứng viên. Bốn nhóm độc lập và tám fault pairs evaluable vẫn là mục tiêu, hiện đã xác minh 0. Hai execution mỗi đường là lặp trong nhóm. Mỗi execution cần approval một POST mới. Hai Normal là chỉ số riêng. Cascade là propagation và Retry Exhaustion là handling, không cộng thêm họ. Có thể xem Retry A trong phân tích phụ, chung grouping với Product 503 nếu chưa có provenance khác biệt.

Verifier offline so mechanism, vị trí, edge và retry. Chính báo cáo thay đổi theo field phân biệt signature giống nhau, biến thể liên quan và ứng viên khác biệt. Tên, seed, trace ID không chứng minh độc lập. Curator kiểm deployment digest và campaign, các template gần trùng và evidence quan sát trước khi duyệt độc lập. Status luôn UNVERIFIED trong tool này. Loại mọi smoke/pilot/historical đã dùng.

Nếu đủ điều kiện, thiết kế tối thiểu 10 cặp, tối đa 20 lượt LLM cho phần tối thiểu, 0 retry, dưới trần 17 cặp/34 lượt. Cần đủ 8 fault pairs thực sự scorable ở hai mode sau adjudication. Nếu hụt mẫu chỉ báo coverage và kết quả thăm dò. Không tạo eligible run trong bước này.

Thứ tự đề xuất nghiệm thu sau phê duyệt riêng là Normal A → Processing A → Timeout A → Database A → Cascade A. Hai đường đầu có bằng chứng live trước khi gắn gate. Timeout A cần xác minh deadline và capture event về muộn; Database A cần chứng minh request DSN thất bại trong khi DB vẫn healthy; Cascade A cần chuỗi span Product 503 và Order 502, cùng grouping bảo thủ với Retry A. Ba đường sau cần chuyển collector legacy sang luồng gated rồi chạy từ fixture trước nghiệm thu live. Các lượt HDFS và OpenAI nằm ngoài phạm vi.
