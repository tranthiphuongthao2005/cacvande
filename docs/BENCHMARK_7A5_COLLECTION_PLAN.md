# Kế hoạch collection chưa phê duyệt

Thứ tự dự kiến Normal, Service Unavailable, Processing Failure, Retry Exhaustion, Cascade, Timeout và Database Failure. Bỏ qua slot DESIGN_BLOCKED cho tới khi có thiết kế và approval riêng. collection_batches.json gắn bước kiểm chứng với từng nhóm cấu hình.

1. Preflight phạm vi lab, quyền vận hành, hiện trạng Compose, CPU/RAM/disk, image/config digest và DB/ELK healthy. Dùng workspace output mới, fixture tách biệt và không ghi bí mật. Chụp lại cùng thông tin ở postflight.
2. Mỗi batch tối đa 4 request mục tiêu và 8 request setup. Readiness polling hạch toán riêng. Dừng trước config kế tiếp nếu không verify activation; không bù lượt lỗi tự động. Tối đa 2 execution mỗi config.
3. Kiểm read-back fault và dấu hiệu theo cohort_plan.json. Đóng producer accounting/source seal, đối chiếu Docker và ES inventory/payload, giữ receipt, late/duplicate reconciliation và trạng thái handoff. Timebox cố định 420 giây sau hoàn thành request. Lưu dossier riêng và cặp snapshot bất biến với SHA-256.
4. Rollback trong finally bằng cấu hình Compose baseline, kiểm lại state, tránh xóa volume. Gate yêu cầu hash khớp, provenance, event không overlap, pairing đúng và no leakage. Nhãn và độc lập chờ reviewer/operator riêng.

Collector 7A.4 hiện hỗ trợ một campaign mỗi lần gọi và scenario dựng sẵn. Cần duyệt adapter nhiều execution, caps và đường dẫn candidate trước khi dùng plan này để thu. Audit 7A.5A chỉ dùng công cụ offline.

Provider dự trù 28 cặp, 56 lượt gọi, 0 retry bổ sung. Ngân sách giả định 8.192 input token mỗi call gồm toàn request và 800 output token, tối đa danh nghĩa 458.752 input và 44.800 output. Evidence cap 7.000 ASCII bytes của app khác giới hạn token. Trước khi chạy phải kiểm bằng tokenizer/bộ đếm phù hợp snapshot và bao gồm prompt, schema và overhead. Process cap hiện tối đa 50 nên cần chia tranche với sổ đếm toàn chiến dịch trước khi chạy. Với đơn giá triệu token I và O, chi phí dự toán USD là 0,458752 × I + 0,0448 × O. Chờ model, nguồn giá và hard cap được phê duyệt, nên phí USD hiện chưa xác định.
