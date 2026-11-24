# Rubric chấm báo cáo LLM

Mỗi người chấm nhận report bất biến, ID ngẫu nhiên và evidence packet tương ứng; ẩn nhãn mode nếu có thể. Số lượng service vẫn có thể tiết lộ scope, cần ghi hạn chế này. Hai reviewer chấm độc lập; giữ từng phiếu và ghi disagreement trước khi adjudication. Reviewer thứ ba hoặc phiên đồng thuận có lý do chọn adjudicated record. Lưu người chấm, trạng thái, ID cấu hình, event IDs thực gửi và fingerprint output gốc trong sổ chấm. Không sửa response sau khi chấm. LLM được đánh giá không làm người chấm duy nhất.

| Mục chấm | Cách ghi |
|---|---|
| Cause / service | True nếu phù hợp một variant đã khóa và có căn cứ; false nếu sai, lẫn symptom hoặc khẳng định trái evidence; null nếu nhãn UNVERIFIED, không áp dụng hoặc abstain. Chấm service trên variant phù hợp. |
| Claim | Mỗi mệnh đề quan trọng có claim_id, trích dẫn event IDs và verdict SUPPORTED, UNSUPPORTED, HALLUCINATED, hoặc UNRATEABLE. |
| Recommendation | Một verdict true/false/null cho mỗi đề xuất theo mức liên quan, khả năng kiểm tra và điều kiện giả định. |
| Completeness | Ghi nhận model thừa nhận thiếu bằng chứng và tránh suy luận từ vắng log, mức true/false/null. |
| Provider | OK với output dùng được, PROVIDER_FAILURE khi có lỗi hoặc output bị loại, MISSING khi chưa có kết quả; giữ danh sách lỗi ở log thực nghiệm. |

Template phiếu: trace_id, mode (điền lại sau chấm), reviewer_id, adjudicated, model_name, config_sha256, provider_status, analysis_status, input_event_ids, cause_correct, service_correct, completeness_acknowledged, claims, recommendations, latency_ms, input_tokens, output_tokens, cost_usd. Dùng schema `adjudicated_review` trong artifact JSON. Ghi lại các claim sai kể cả khi LLM abstain.

## Định nghĩa thao tác

| Metric | Tử số / mẫu số |
|---|---|
| Root Cause Accuracy | Cause đúng / báo cáo thành công ANALYZED với nhãn đã xác minh và được chấm. Một variant đã khóa hợp lệ được tính đúng. |
| Root Cause Service Accuracy | Service đúng / report thành công ANALYZED có nhãn service xác minh và được chấm. Normal hoặc nhãn không có service là null. |
| Evidence Reference Validity | Số lần dẫn ID nằm trong evidence thực gửi / tổng lượt dẫn. Claim không dẫn ID vẫn đi vào rubric support. |
| Evidence Support Rate | Claim do người chấm xác nhận bằng chứng hỗ trợ / tất cả claim chấm được. |
| Unsupported Claim Rate | UNSUPPORTED cộng HALLUCINATED / tất cả claim chấm được. |
| Hallucination Rate | Claim bịa một event, entity, thuộc tính hoặc quan hệ dưới dạng sự kiện đã xác nhận, hay mâu thuẫn trực tiếp với evidence / tất cả claim chấm được. Giả thuyết có ghi điều kiện nhưng chưa đủ evidence thuộc UNSUPPORTED khi không được hỗ trợ. |
| Recommendation Relevance | Đề xuất phù hợp / đề xuất chấm được. |
| Abstention Rate | INSUFFICIENT_EVIDENCE / output OK. Provider failure và missing ghi riêng. |
| Latency, tokens và cost | Tổng/đếm mẫu có giá trị quan sát để tính mean, kèm median; null khi không đo. Chỉ điền cost theo bảng giá snapshot có nguồn. |
| Context completeness | Số snapshot COMPLETE, PARTIAL, UNKNOWN theo mode trên toàn tập đã khóa. |

Mẫu số 0 cho null. Provider failure, missing, abstention và UNVERIFIED làm giảm coverage. Báo riêng các số này và số cặp đủ điều kiện. Nếu muốn thêm end-to-end accuracy tính abstention/failure là không thành công, phải khóa phép đo riêng trước evaluation; bộ tổng hợp hiện dùng accuracy có điều kiện.
