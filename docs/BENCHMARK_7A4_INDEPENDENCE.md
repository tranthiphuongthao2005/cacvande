# Độc lập và eligibility

Các cấp gồm HTTP execution riêng, cấu hình causally khác biệt và cơ chế lỗi riêng. Campaign đầu dùng lại tham chiếu lab và cùng topology. Audit giữ một nhóm campaign, so tập template theo Jaccard với pilot, so chữ ký chính xác service/message/status với audit 7A và pilot, cùng nhận dạng trùng ID. Để đánh giá chính thức, thêm kiểm ngày, workload family, cấu hình và chuỗi gần trùng trên tất cả campaign trước khi tách nhóm.

Single chọn Order trước khi xem nhãn. Cross chỉ dùng context API với quan hệ đã được quan sát. Các cặp không nhận nhãn, reviewer status hay expected chain. Dossier và mẫu review để riêng trong labels, không đi vào runtime. Không chấm hay chọn trace bằng LLM.

Ứng viên chỉ là bản ghi phục vụ eligibility audit. `TECHNICALLY_VALID` nói về telemetry và pair, `LABEL_PENDING_REVIEW` nói về nhãn, `EXCLUDED` áp dụng khi không thể đưa vào evaluation. Có chữ ký trùng lịch sử thì giữ ở development ngay cả khi reviewer xác minh nhãn. Thiếu ACK được report riêng, không tự loại nếu protocol cho phép PARTIAL/UNKNOWN. Không khóa evaluation khi thiếu nguồn reviewer, nguồn config độc lập hoặc phê duyệt.
