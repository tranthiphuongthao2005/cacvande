# Protocol và taxonomy implementation candidate

Hai file protocol_candidate.json và taxonomy_candidate.json có status IMPLEMENTATION_CANDIDATE và actual_approval_status PENDING. Taxonomy giữ cơ chế dependency unavailable, timeout, database connection failure, processing failure, Normal và Other/unknown. Cascade thuộc propagation, retry exhausted thuộc handling, cả hai có thể cùng xuất hiện khi có bằng chứng riêng. Không coi HTTP symptom là cơ chế.

Primary là mean của hiệu số nhị phân Cross−Single trên fault pairs VERIFIED và chấm được ở cả hai mode. Báo mẫu số, coverage và số cặp loại. Normal false attribution dùng Normal VERIFIED/ANALYZED chấm được và báo riêng. Abstention, evidence support, unsupported claims, latency, cost và provider failures giữ mẫu số đã đề xuất ở 7A.5H. Missing, invalid output và provider failure được ghi riêng; báo sensitivity end-to-end tính thiếu kết quả là không thành công. Feasibility mô tả, không mặc định CI hoặc significance.

Single/Cross cùng trace, model snapshot, decoding, rubric và prompt; khác phạm vi context. Single trước budget là Order projection của Cross. Không gửi ground truth hoặc reviewer artifact vào prompt. Ghi completeness từng mode và coverage. Có thể bao gồm PARTIAL/UNKNOWN theo chính sách được duyệt. Source TRACE_COMPLETE không được nâng, Filebeat handoff UNCONFIRMED giữ nguyên, sensitivity theo completeness nếu đủ dữ liệu. Planner đọc classification hiện có, không thay source snapshot. Không đưa Normal A hoặc Processing A vào set blind.

Giữ nguyên v1 và v2 draft. Candidate chờ operator duyệt và tạo frozen protocol riêng. Trước inference chỉ ước lượng số cặp đủ nhãn và snapshot; evaluable thật chỉ xác định sau output và adjudication.
