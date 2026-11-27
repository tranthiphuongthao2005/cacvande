# Protocol đánh giá 7A.5A

Trong cùng mô hình LLM và cấu hình suy luận, cross-service context có cải thiện độ chính xác phân tích nguyên nhân và chất lượng bằng chứng so với single-service context hay không?

Primary là hiệu số Cross trừ Single của tỷ lệ root cause đúng trên các cặp fault chấm được ở cả hai mode. Dùng rubric hiện có và báo toàn bộ mẫu số. Trên Normal, báo false attribution trong output ANALYZED, coverage và abstention riêng. INSUFFICIENT_EVIDENCE được giữ null trong primary và tính không thành công trong sensitivity end-to-end cho fault; ghi riêng provider failure và missing. Nếu có nhiều nguyên nhân hợp lý, reviewer ghi trước tập variant cause/service và evidence cho từng variant. Output khớp bất kỳ variant đã duyệt nào và có căn cứ được tính đúng.

Secondary gồm evidence support và unsupported causal claims do reviewer chấm, abstention, latency, token input/output và cost. Event ID hợp lệ chỉ xác nhận dẫn chiếu. Hai người chấm output độc lập, che mode nếu khả thi, ghi disagreement và adjudicate trước khi tổng hợp.

Giữ một Cross v2 snapshot bất biến mỗi trace, chốt tại cutoff 420 giây sau kết thúc request; chụp Single bằng projection chính xác của các event Order trong Cross. Cùng sanitizer, prompt, model snapshot và budget; lưu event IDs gửi thật và phần bị lược theo mode. Dossier và nhãn nằm ngoài provider input, không dùng để chọn/sửa event. Giữ provenance COMPLETE/PARTIAL/UNKNOWN. Cặp thiếu ACK nhưng đã đối chiếu event và có evidence đánh giá được có thể vào phân tích nếu được duyệt; không nâng completeness. Loại khi sai scope, thiếu Order, duplicate, unreconciled, hash lệch, overlap hoặc thiếu nhãn xác minh. Phân tầng sensitivity theo Cross completeness và mô tả completeness riêng mỗi mode.

Tối đa 28 cặp, 14 cụm cấu hình theo thiết kế trước khi gộp. Báo mẫu số thực, counts discordant, hiệu số từng cặp, accuracy theo family, độ phủ và kết quả theo cụm. Feasibility dùng mô tả, không CI mặc định. CI bootstrap ở nghiên cứu mở rộng chỉ khi khóa ngưỡng cụm trước, có đủ cụm độc lập, giữ whole cluster và hai mode trong lần lấy mẫu. Không suy luận ý nghĩa thống kê từ nhiều trace chung config hoặc campaign.

Manifest evaluation_protocol.json là dự thảo có version. Outcome và quy tắc được đề xuất trước output. Trước inference cần operator ký duyệt, điền snapshot model, khóa SHA-256 canonical và các fingerprint prompt/schema/rubric/build/snapshot cùng tham số suy luận và bảng giá. Mọi điều chỉnh được version hóa trước lần gọi đầu tiên.
