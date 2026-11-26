# Readiness cho đánh giá LLM

| Metric | Công cụ đã có | Dữ liệu còn thiếu |
|---|---|---|
| Root cause và service accuracy | Rubric, schema quyết định và aggregator | Nhãn độc lập VERIFIED và output provider trên tập khóa |
| Evidence reference validity | Validator ID, scope và event field | Output thật hoặc adjudicated rows |
| Evidence support, unsupported causal claims | Rubric và tổng hợp claim-level | Hai reviewer và adjudication, so payload nguồn |
| Abstention | Trạng thái INSUFFICIENT_EVIDENCE và aggregator | Output thật; report riêng provider failure |
| Paired comparison | Snapshot validator, per-trace delta và bootstrap nhóm có điều kiện | Peer outputs cùng model/config, nhóm độc lập và đủ coverage |
| Latency / input-output tokens | API metadata và summary | Lượt provider thật, cùng setup; latency mock không đại diện |
| API cost | Metadata và công thức dự trù | Usage thật và bảng giá đúng snapshot/provider |

Chưa thể tính bất kỳ metric hiệu năng LLM thật nào. Cần credentials, model đã duyệt, phê duyệt chi phí, tập chưa từng xem, nhãn độc lập và protocol khóa. Phân biệt hiện tượng quan sát, valid event ID và claim nhân quả được hỗ trợ.

## Khoảng trống nghiên cứu Detection

BGL → HDFS đã có smoke-scale cross-domain, checkpoint BGL 100 episodes và HDFS final đã khóa. Báo cáo lịch sử ghi Binary F1 mean Single 0,6473, Multi 0,7897; ROC-AUC 0,6104 và 0,9116; FPR 0,0265 và 0,3415. Đây là kết quả từ recovery đã kiểm toán, 20 seed chia sẻ checkpoint và query HDFS. Không đọc nhãn final hoặc chạy lại. [Bảng MeCoLog đã lưu](../../tuanmartin-MeCoLog-8c446ac/real_smoke_cpu/thesis_results/RESULTS_TABLES.md)

Detection vẫn NOT_READY_FOR_SCORING vì chưa xác thực biểu diễn Microservices cho encoder và chưa có support protocol độc lập. Catalog có thể tạo tensor đúng shape nhưng key positional chỉ giảm OOV về ID, chưa xác minh tương đương ngữ nghĩa; padding cao. Để đánh giá detection, cần biểu diễn đã kiểm tra domain shift, support/development/evaluation tách theo group, nhãn Normal/Anomaly có provenance, test coverage và threshold khóa trước query. Báo FPR, recall, ranking, prevalence và sensitivity theo độ dài/campaign khi có dữ liệu.

Chưa có căn cứ tuyên bố MeCoLog phát hiện anomaly tự động trong Microservices, tổng quát hóa sang hệ thống khác hoặc workflow LLM đã nâng chất lượng phân tích. Các batch được kích hoạt theo scenario.
