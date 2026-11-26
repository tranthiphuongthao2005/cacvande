# Báo cáo sự cố final evaluation

Trạng thái **lượt final đã mở dữ liệu và dừng khi ghi artifact**. Chưa có metrics final đã xác minh.

Preflight xác nhận lock SHA-256 308e29ba2c48ff92c4ea3230206c99194daeb1e85a5832088c5b635c8285c63b, checkpoint, scorer đã audit, hai NPZ final, lineage và chín file Python gốc. Checkpoint strict-load đủ 32 tensor. Hai pool nạp thành công, gồm 20 Normal và 20 Anomaly support, 100 Normal và 100 Anomaly query.

Lượt chạy tiến qua vòng 40 tổ hợp phương pháp và seed trong bộ nhớ. Kiểm tra weights và hash đầu vào cuối vòng chạy đã qua. Tại giai đoạn predictions_integrity, ghi final_support_seeds.json dừng ở trường short. Bộ đếm được tạo từ biểu thức so sánh NumPy và có kiểu int32. json.dump không tuần tự hóa được kiểu đó. Traceback nằm trong incident.json. File support JSON ghi dở được giữ để bảo toàn audit trail.

Không có final_runs.csv, final_predictions.csv, final_summary.json, paired_final_comparison.csv hay final_length_analysis.json. Điểm và metrics chỉ nằm trong bộ nhớ tiến trình đã thoát. Không báo cáo kết quả hoặc số fallback từ lần chạy này. Thời gian lệnh tới lúc lỗi là khoảng 6,61 giây. Không có số đo peak RAM hoàn chỉnh.

Đối chiếu checksum sau sự cố xác nhận 16 file được bảo vệ khớp, gồm chín file Python gốc, bốn NPZ cũ, checkpoint và hai NPZ final. Runner giữ nguyên thư mục kết quả đã tồn tại làm chốt một lần chạy.

Để phục hồi, cần quyết định có cho phép một lần chạy lại được ghi nhận rõ là recovery hay không. Phương án đề xuất là ép các bộ đếm về Python int ở ranh giới serialization, kiểm thử xuất báo cáo với fixture không chứa dữ liệu final, giữ nguyên tất cả hash của protocol/model/scorer/NPZ, rồi ghi kết quả recovery ở thư mục riêng. Chưa sửa runner hoặc chạy lại final.
