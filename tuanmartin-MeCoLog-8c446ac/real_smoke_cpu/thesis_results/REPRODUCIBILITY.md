# Tính tái lập và minh bạch

Protocol khóa có SHA-256 308e29ba2c48ff92c4ea3230206c99194daeb1e85a5832088c5b635c8285c63b. Pre-final audit replay 40 lượt development và 8.000 score với sai khác tối đa bằng 0. Lock ghi fingerprint scorer, checkpoint, feature, seed và quy tắc fallback. [Protocol](../pre_final_audit_seed123/frozen_protocol.json) · [Audit](../pre_final_audit_seed123/audit_summary.json)

Lần final ban đầu đã chạy inference nhưng lỗi JSON với NumPy int32 khi ghi manifest support; metrics xác minh chưa được lưu. Thư mục sự cố giữ nguyên. Recovery được phê duyệt chỉ thay wrapper serialization và thư mục ghi. Fixture không chứa final data và preflight đều qua. Protocol, scorer, checkpoint, seed, threshold và NPZ giữ nguyên. Recovery lưu 40 lượt và 8.000 dự đoán, rồi hậu kiểm metrics từ CSV. Không tuning sau khi mở final. [Sự cố](../final_evaluation_locked_seed123/incident.json) · [Recovery](../final_recovery_seed123/recovery_manifest.json)

Bộ báo cáo này chỉ đọc CSV, JSON và Markdown. Metrics final lấy từ recovery. Metrics được tính lại bằng scikit-learn trên score và predictions đã lưu. ARTIFACT_MANIFEST.json ghi SHA-256 từng nguồn đã đọc, đầu ra và trạng thái kiểm tra. Không có thao tác nạp checkpoint, NPZ hoặc chạy inference.

Từ thư mục chứa model.py, đọc báo cáo và dữ liệu hình bằng PowerShell:

    Get-Content -Encoding utf8 .\real_smoke_cpu\thesis_results\THESIS_SUMMARY_VI.md
    Get-Content -Encoding utf8 .\real_smoke_cpu\thesis_results\RESULTS_TABLES.md
    Import-Csv .\real_smoke_cpu\thesis_results\FIGURES\04_paired_delta_binary_f1.csv
    Get-Content -Raw -Encoding utf8 .\real_smoke_cpu\thesis_results\ARTIFACT_MANIFEST.json
