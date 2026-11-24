# Readiness 7A.7

Stability trước live đạt 40/40 HTTP 200 qua 10 vòng, nghỉ 10 giây, timeout 4 giây. Đã tạm dừng đúng sáu container Kibana, n8n, LLM Analysis, Incident Adapter, Detection, autoscale-demo-control-plane đang chạy. Tất cả đã khởi động lại thành công và báo Up. Sau khôi phục, User và Product timeout khoảng 4 giây; Order và Context 200 trong 3,048 và 1,271 giây. Core DB, ES và Filebeat healthy theo Docker. n8n và Kibana health starting lúc quan sát. Fault flags và accounting scope trống, runtime lock không tồn tại.

Collection hoàn thành. Benchmark vẫn chưa khóa. 10 ứng viên hợp lệ kỹ thuật, 10 NEEDS_REVIEW và UNVERIFIED, 0 ground truth VERIFIED, 0 nhóm độc lập VERIFIED, 0 blind-eligible. Trước 7A.8 cần reviewer độc lập, quyết định grouping/overlap và protocol/manifest khóa riêng. Tất cả chữ ký quan sát theo service/message/status trùng acceptance của cấu hình tương ứng, nên chỉ hỗ trợ luận điểm execution mới trên cấu hình đã thấy. Cần xác nhận lại runtime ổn định với tải đã khôi phục trước phiên live khác. Không gọi OpenAI, không HDFS final.

Full regression 130 PASS, 1 FAIL. Fixture Processing tái hiện Product lookup timeout trước fault hook. Xử lý tính ổn định fixture và đánh giá lại runtime nếu 7A.8 cần chạy live. Kết quả thu thật giữ nguyên. 190/190 cohort hash, 95/95 acceptance hash và 63/63 MeCoLog fingerprint khớp.
