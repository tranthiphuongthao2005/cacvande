# Protocol đề xuất 7A.5H

Primary là mean của từng hiệu số nhị phân Cross đúng − Single đúng trên tập cặp fault có ground truth VERIFIED và cả hai mode ANALYZED/chấm được. Đúng cần khớp một biến thể cause đã khóa, service nếu biến thể yêu cầu, và evidence hỗ trợ. Partial áp dụng ở mục phụ và tính 0 trong primary nếu cặp chấm được. Không suy ra cause từ symptom. Báo N eligible trước inference, N paired scorable, N loại và lý do theo mode, số discordant theo hai hướng, và giá trị primary null khi denominator = 0.

| Chỉ số | Mẫu số |
|---|---|
| Abstention | INSUFFICIENT_EVIDENCE trên output hợp lệ, gồm ANALYZED và INSUFFICIENT_EVIDENCE |
| Unsupported causal claims | Claim UNSUPPORTED hoặc HALLUCINATED chia claim chấm được, giữ claim thiếu citation trong mẫu số nếu vẫn chấm được |
| Evidence support | Claim SUPPORTED chia claim chấm được |
| Normal false attribution | Số Normal VERIFIED bị quy sai cho lỗi chia số output Normal ANALYZED chấm được |
| Latency và cost | Latency trên attempt đo được, cost trên attempt có usage và bảng giá, báo coverage và tổng chi phí gồm lỗi nếu có usage |

Provider failure, invalid output và missing ghi riêng trên số run/mode đã đăng ký, không gộp vào abstention. Báo phụ end-to-end trên toàn bộ fault VERIFIED đã khóa, tính missing, provider failure và abstention là không thành công. Báo conditional result cùng coverage để tránh so sánh thiên lệch do các mode abstain khác nhau. Chỉ số theo claim ghi mẫu số theo mode và số output đóng góp. Chi phí thiếu usage hoặc bảng giá ghi null, không điền 0.

Ghép đúng cùng trace. Single là Order projection của Cross trước giới hạn token, lưu event IDs thực gửi, cùng model, decoding, prompt, sanitizer và budget. Ground truth, hồ sơ và reviewer quyết định ở khu vực riêng. Output chấm theo ID ẩn mode khi khả thi, hai người chấm và adjudication. Snapshot bất biến theo cutoff đã duyệt, receipt và checksums. Lịch chạy mode cần được cân bằng hoặc khóa để latency ít bị ảnh hưởng bởi thứ tự.

Feasibility báo mô tả, không mặc định CI hoặc significance. Nếu operator duyệt phân tích mở rộng, preregister cách resample toàn bộ cụm độc lập, giữ cả hai mode và trace trong cụm, CI 95% cùng seed và số lần lặp. Chỉ dùng khi số cụm và thiết kế đủ căn cứ; nếu chưa có ngưỡng đã duyệt hoặc không đủ cụm, CI null. Báo sensitivity theo completeness và family với mẫu số mỗi nhóm.
