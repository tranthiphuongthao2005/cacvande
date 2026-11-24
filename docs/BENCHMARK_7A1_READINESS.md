# Readiness 7A.1

**Pilot hợp lệ về thu thập, chưa sẵn sàng khóa evaluation.** Không có trace đủ điều kiện blind evaluation. Pilot dùng một campaign, một nhóm bảo thủ và hai biến thể. Bốn Cross snapshot là PARTIAL, bốn Single snapshot là UNKNOWN. Bốn request riêng vẫn thuộc cùng cụm phụ thuộc và chưa đủ để ước lượng accuracy hay suy luận thống kê.

Cần campaign mới có workload và propagation khác nhau, thu đủ fault families cho mục tiêu đã chọn, bằng chứng độc lập và adjudication nhãn. Nhóm trial từng dùng để phát triển tooling hoặc trong báo cáo được đánh dấu đã xem. Trước khi khóa, curator kiểm leakage, scope Order, provenance và coverage theo fault family rồi xin phê duyệt. Kiểm tra độ chính xác mong muốn bằng khoảng bất định theo số nhóm độc lập; dùng mức 14–28 trace cho dry-run và 42–84 trace chỉ là mức lập kế hoạch từ 7A. Không tự mở rộng batch khi pilot còn blocker.

[Run manifest](../experiments/benchmark_7a1_pilot_seed124/run_manifest.json) · [Independence report](../experiments/benchmark_7a1_pilot_seed124/independence_report.json) · [Checksum manifest](../experiments/benchmark_7a1_pilot_seed124/checksum_manifest.json)

Validator đọc lại bốn run và kiểm đủ 33 artifact checksum. Audit 7A tái lập giống artifact đã lưu. 63 fingerprint MeCoLog khớp. Detection vẫn NOT_READY_FOR_SCORING. Không chạy HDFS final, không tạo prediction và không gọi provider thật.

Pytest đạt **57/57** trong 55,54 giây, gồm PostgreSQL lab riêng và bốn fixture 7A.1. Có ba cảnh báo deprecation có sẵn. Fixture kiểm manifest, duplicate và isolation, trường hợp telemetry lệch hoặc thiếu, behavior check, group-aware split, pairing và hash snapshot. Sau khôi phục fault flags, User, Product và Order đều trả 200 tại /ready.

Lệnh PowerShell và cách chạy bản mới nằm trong [tài liệu collection](BENCHMARK_COLLECTION.md). Bundle hiện tại giữ nguyên để đối chiếu.
