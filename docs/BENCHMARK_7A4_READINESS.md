# Readiness 7A.4

**Đã kiểm chứng batch đầu. Chưa đủ điều kiện evaluation.** Một cơ chế Product unavailable được kiểm chứng với một cấu hình thử, 0 cấu hình độc lập được xác minh, 1 nhóm campaign. Một run đạt quality gate kỹ thuật. Một bản ghi candidate audit được tạo và bị loại khỏi evaluation vì nhãn chờ review, signature trùng lịch sử và chưa có phê duyệt khóa protocol. Không loại run khỏi tập kỹ thuật chỉ vì handoff chưa được xác nhận. Số eligible blind là 0.

Regression đạt **72/72 pytest** với PostgreSQL lab riêng và ba cảnh báo deprecation có sẵn. Sau thay đổi lưu preflight đã chạy lại bảy test campaign/accounting, tất cả đạt. Kiểm lại 17 SHA-256 của bundle batch, 33 pilot, 9 audit 7A.2, hai bundle smoke 7A.3/7A.3B có 4 file mỗi bundle và 63 fingerprint MeCoLog. Audit lịch sử 7A tái lập đúng. Detection vẫn NOT_READY_FOR_SCORING, không chạy HDFS final.

Blocker là adjudication độc lập, cohort đa dạng hơn có cấu hình thực sự độc lập và phương án khóa split được người vận hành phê duyệt. Batch sau cần phê duyệt trước. Không chạy đánh giá LLM hoặc gửi notification ngoài.

[Ứng viên và lý do loại](../experiments/benchmark_7a4_batch01/evaluation_candidates.json) · [Độc lập](../experiments/benchmark_7a4_batch01/independence_report.json) · [Lệnh tái lập PowerShell](BENCHMARK_7A4_COLLECTION_PLAN.md)
