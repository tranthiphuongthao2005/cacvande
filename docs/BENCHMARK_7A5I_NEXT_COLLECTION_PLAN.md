# Kế hoạch collection tiếp theo 7A.5I

Có thể chạy ngay offline reviewer validation, audit checksums và dry-run. Có thể bàn giao dossier và yêu cầu operator xác nhận reviewer độc lập. Không chạy collection hoặc provider trong giai đoạn này.

Trước collection cần phê duyệt taxonomy/protocol, cơ chế grouping, số lượng, policy incomplete và từng fault adapter. Ưu tiên tạo candidate mới tách khỏi development, kiểm preflight, bounded POST budget, activation, telemetry, rollback và cutoff. Không dùng smoke/pilot đã quan sát làm blind candidate. Giữ manifest và ground truth ngoài context.

Dự trù tối đa 17 cặp và 34 calls, 0 retry. Mục tiêu tối thiểu 8 fault pairs evaluable, 4 nhóm fault độc lập xác minh và 2 Normal pairs. Seed/trace ID khác không đủ xác nhận độc lập. Sau inference nếu thiếu mẫu chỉ báo độ phủ và kết quả thăm dò. Trước inference cần operator phê duyệt riêng model snapshot, decoding, credential activation, token preflight và bảng giá/cost ceiling. Không đặt USD khi chưa duyệt.

```powershell
.\.venv\Scripts\python.exe -B -m tools.benchmark_readiness_7a5i
.\.venv\Scripts\python.exe -B -m tools.benchmark_readiness_7a5i --reviewer-packet .\experiments\benchmark_7a5\processing_a_reviewer_handoff_7a5h
.\.venv\Scripts\python.exe -B -m tools.validate_7a5d
```
