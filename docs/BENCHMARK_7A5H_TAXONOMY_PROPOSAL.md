# Taxonomy đề xuất 7A.5H

Đề xuất giữ hai chiều của v2. Cơ chế gốc là nguyên nhân có evidence. Propagation/handling mô tả tác động và cách xử lý sau khi lỗi xảy ra, cho phép nhiều giá trị nếu có evidence cho từng giá trị.

| Cơ chế gốc | Tiêu chí evidence |
|---|---|
| Normal / no fault | Luồng thành công, cấu hình không kích hoạt fault và đủ evidence trong phạm vi quan sát |
| Dependency unavailable | Dependency trả 503 hoặc mất kết nối, có bằng chứng caller hoặc dependency phù hợp |
| Dependency timeout | Deadline bị vượt và evidence về thời điểm hoặc lỗi timeout |
| Database connection failure | Lỗi kết nối repository có phạm vi, không suy ra DB crash chỉ từ 503 |
| Processing failure | Evidence về processing stage và lỗi nghiệp vụ |
| Other / unknown | Phân biệt other có cơ chế được mô tả nhưng ngoài danh mục với unknown thiếu bằng chứng |

Handling gồm Local, Propagated, Retry exhausted và Unknown. Propagated cần cạnh caller, callee và hệ quả liên quan. Retry exhausted cần policy, attempt count, lỗi retryable và final outcome. Một lần thử với log exhausted chưa chứng minh retry. Cascade là propagation trong dữ liệu hiện có; Dependency Unavailable có thể là cơ chế của cả Cascade và Retry Exhaustion. Không đếm cùng chuỗi Product 503 như ba cơ chế độc lập. Normal dùng handling rỗng. Unknown handling không được gán đồng thời với handling đã quan sát trong cùng phạm vi. Unknown mechanism không chấm primary nếu ground truth không xác định được causal attribution.

Fault injection, sự kiện quan sát, root cause và HTTP symptom giữ riêng trong hồ sơ. Operator cần duyệt taxonomy trước khi áp dụng. Dữ liệu lịch sử giữ nguyên.
