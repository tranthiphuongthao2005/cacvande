# Configuration independence 7A.7

Bốn họ lỗi ứng viên là processing failure sau dependency lookup tại Order, dependency timeout tại Order→Product với delay phía Product, database connection failure tại request DSN Order và dependency unavailable qua Product→Order. Cascade ghi propagation. Retry processing độc lập với số attempt và không thêm một root mechanism. Normal là negative control.

Hai repetition cùng cấu hình thuộc cùng candidate group. Theo provenance, cả năm adapter đã được sử dụng trong acceptance, nên cấu hình mới theo nghĩa unseen configuration chưa được chứng minh. Kiểm overlapping template hoặc signature với development, pilot và acceptance là bước curator cần làm. Không coi seed, campaign, timestamp hoặc trace ID mới là cấu hình độc lập. Configuration fingerprints gồm code fault, storage, Compose, gate và collector cùng status UNVERIFIED. Chỉ reviewer/operator thực mới xác minh độc lập. Xem configuration_groups.json.

Audit sau collection tính signature từ tập bộ ba service, message và HTTP status quan sát được. Cả 10/10 run khớp với acceptance của cấu hình tương ứng. Mỗi cặp repetition có một signature chung. Điều này xác nhận overlap về biểu hiện, dù ID và evidence không trùng. Không nâng trạng thái độc lập hoặc khẳng định unseen-fault generalization.
