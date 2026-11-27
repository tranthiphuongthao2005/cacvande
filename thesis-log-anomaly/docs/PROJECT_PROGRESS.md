# Tiến độ sau merge và kế hoạch tiếp theo

Cập nhật ngày 27/11/2026, trên nhánh `nga` sau merge `main` (`b48741b`). Trạng thái dưới đây dựa trên mã và artifact hiện có trong repo; các phép thử runtime sau merge chưa được chạy lại.

| Công việc | Trạng thái cập nhật | Bằng chứng / giới hạn |
|---|---|---|
| 9.7 – Kiểm thử E2E thực tế | Tạm hoãn | Thiết lập đầy đủ chịu áp lực RAM. n8n đã chạy qua webhook với LLM mock, nhưng Detection vẫn trả `NOT_READY_FOR_SCORING`; chưa có phép thử Detection → Context → LLM → n8n bằng provider thật. Xem `N8N_VERIFICATION.md`, `SCORING_READINESS.md`. |
| 10.1 – Monitoring Dashboard | Chưa làm | ELK/Kibana đã có trong `compose.logging.yaml`; chưa thấy cấu hình dashboard hoặc saved objects trong repo. |
| 10.2 – Incident Dashboard | Chưa làm | Incident adapter đã lưu SQLite và có `GET /incidents/{identity}`; chưa có màn hình danh sách, lọc và xem chi tiết sự cố. Xem `app/incident_workflow.py`. |
| Thực nghiệm LLM Single/Cross-service | Thành viên khác phụ trách; chưa có kết quả 10 cặp/20 lượt trong repo | Cohort 10 cặp đã thu thập. Kế hoạch 20 lượt hiện `authorized: false` và khóa prompt `rca-evidence-v1`; smoke thành công dùng v4. Cần thống nhất protocol với thành viên phụ trách trước khi dùng kết quả. Xem `BENCHMARK_7A7_COLLECTION_RESULTS.md` và `experiments/benchmark_7a8r_exploratory/evaluation_plan.json`. |
| 11.1 – Tích hợp LLM thật | Hoàn thành smoke Gemini; chưa hoàn thành tích hợp workflow | Smoke 009 chạy Gemini thật cho Single và Cross, cả hai PASS/HTTP 200. Workflow n8n hiện yêu cầu provider `mock`, Gemini còn bị giới hạn theo trace và ngân sách smoke. Xem `experiments/gemini_smoke_7b1/gemini-smoke-7b1-009.execution.json`, `app/incident_workflow.py`, `app/llm_api.py`. |
| 11.2 – Đánh giá toàn hệ thống | Chưa làm | Cần E2E có đo latency, tài nguyên, lỗi và độ đúng của chuỗi bằng chứng; chưa thể kết luận hiệu quả RCA từ một smoke. |
| Báo cáo, slide, video demo | Cần hoàn thiện | Đã có tài liệu phương pháp/kết quả MeCoLog và các báo cáo kiểm chứng thành phần; cần tổng hợp thành bản khóa luận, slide và kịch bản demo thống nhất. |

## Thứ tự thực hiện

1. **Chốt baseline sau merge.** Chạy lại kiểm thử không integration và audit nghiên cứu; ghi commit, trạng thái Compose và RAM khả dụng. Sửa các tài liệu trạng thái cũ nếu chúng mô tả smoke Gemini là chưa chạy. Điều kiện xong: có kết quả kiểm thử và danh sách blocker hiện thời.
2. **Làm Monitoring Dashboard (10.1).** Tạo dashboard Kibana có thể import lại từ file trong repo, hiển thị lượng request, lỗi theo service, latency, trace ID và tình trạng log. Dùng dữ liệu đã thu để dựng và kiểm tra; chỉ bật Kibana khi cần xem dashboard để tiết kiệm RAM.
3. **Làm Incident Dashboard (10.2).** Bổ sung API đọc danh sách/chi tiết từ incident ledger và giao diện xem trạng thái phân tích, service liên quan, evidence IDs, completeness, validation warnings, replay và notification. Kiểm tra quyền truy cập và tránh lộ khóa hoặc nội dung raw provider.
4. **Hoàn tất tích hợp LLM thật (11.1).** Thiết kế đường gọi Gemini qua incident adapter/n8n thay cho ràng buộc `mock`, giữ giới hạn lượt gọi, timeout, idempotency và evidence validation. Kiểm thử mock trước, sau đó thử một ca thật có ngân sách và ghi receipt. Không dùng smoke 009 làm số liệu đánh giá 20 lượt.
5. **Mở lại E2E (9.7) theo từng tầng.** Đo RAM/CPU lúc chạy; thử scenario → Context → LLM mock → incident, rồi scenario → Context → Gemini → incident. Chạy các nhóm container tuần tự và tắt Kibana khi không cần. Kiểm tra replay, context thiếu, lỗi provider và restart. Chỉ gọi đây là E2E từ Detection khi Detection đã qua gate; hiện `NOT_READY_FOR_SCORING`. Rule-based detector và Hybrid Router trong backlog ban đầu cũng cần được xử lý nếu mục tiêu vẫn là luồng Detection tự động.
6. **Đánh giá toàn hệ thống (11.2).** Khóa tập ca, chỉ số và cách chấm trước khi đo: tỷ lệ hoàn tất, latency từng chặng, RAM đỉnh, xử lý lỗi/replay, chất lượng evidence và giới hạn của RCA. Gộp kết quả 10 cặp Single/Cross do thành viên khác thực hiện sau khi kiểm tra protocol, provenance và review.
7. **Hoàn thiện báo cáo và bảo vệ.** Cập nhật sơ đồ kiến trúc đúng với hệ thống đã chạy, bảng/biểu đồ có nguồn artifact, giới hạn thí nghiệm, slide ngắn và video demo có kịch bản dự phòng khi RAM hoặc provider không ổn định.

Không đánh dấu E2E Detection hoặc đánh giá toàn hệ thống là hoàn thành chỉ từ webhook mock hoặc smoke Gemini đơn lẻ.
