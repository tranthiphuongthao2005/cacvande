# Hồ sơ xác minh ground truth

Audit đối chiếu SHA-256 cấu hình fault, HTTP đã lưu, bản sao Docker và Elasticsearch, span graph và chuỗi kỳ vọng. Mỗi dossier liên kết Order root SERVER → Order CLIENT → User hoặc Product SERVER rồi nối event đã ghi với span. Hai run Normal có User 200, Product 200, Order 201 và không có lỗi trong luồng quan sát. Nhãn ứng viên là normal control, root cause/service null. Phạm vi Normal chỉ là request đã quan sát.

Hai run Cascade khai báo cấu hình Product unavailable. Product SERVER trả 503, Order CLIENT ghi dependency attempt failed cho Product trên span cha của Product SERVER, Order root trả 502. Điều này hỗ trợ giả thuyết Product lookup unavailable là nguyên nhân gần của lỗi Order. Receipt collector ghi hành vi phù hợp với cấu hình. Không có bản ghi độc lập chứng minh fault toggle đã được kích hoạt đúng thời điểm; sự kiện HTTP 502 tự nó chỉ là triệu chứng. Không phát hiện bằng chứng mâu thuẫn trong bốn run.

| Biến thể | Run | Đủ hồ sơ cho review ứng viên | VERIFIED | NEEDS_REVIEW | INCONCLUSIVE đã chấm |
|---|---:|---:|---:|---:|---:|
| Normal | 2 | 2 | 0 | 2 | 0 |
| Cascade | 2 | 2 | 0 | 2 | 0 |

Reviewer độc lập dùng dossier và nguồn telemetry được dẫn. Với Cascade, xem thêm bằng chứng kích hoạt nếu muốn quy nguyên nhân cho chính cơ chế injection. Sao chép form sang file quyết định mới, giữ hash dossier, điền reviewer_id, thời gian có timezone và lý do cho VERIFIED, REJECTED hoặc INCONCLUSIVE. Nếu cần bổ sung, giữ dossier gốc và ghi tài liệu bổ sung riêng. Công cụ xác minh cấu trúc phiếu và binding SHA-256, còn quyền xác nhận danh tính, độc lập và quyết định thuộc người vận hành. Không sửa nhãn pilot hay phê duyệt tự động.

[Dossiers](../experiments/benchmark_7a2_verification/dossiers/) · [Review forms trống](../experiments/benchmark_7a2_verification/review_forms/)
