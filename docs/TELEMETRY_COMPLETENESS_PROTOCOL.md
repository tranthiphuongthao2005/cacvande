# Protocol completeness có thể kiểm chứng

| Trạng thái | Điều kiện |
|---|---|
| REQUEST_COMPLETED | Một root SERVER span kết thúc có application request_completed khớp trace, service, span và thứ tự thời gian. |
| INGESTION_SETTLED | Trusted collector đã đóng capture với tập event ID dự kiến. Mọi ID có xác nhận index, đọc được trong snapshot sau cutoff và sau thời điểm xác nhận của chúng. |
| TRACE_COMPLETE | Hai điều kiện trên đạt, các span kỳ vọng khớp graph đã kết thúc, mỗi event có span, payload Docker khớp ES, và snapshot không có lỗi dữ liệu ảnh hưởng coverage. |

Validator chống thiếu child, parent không tồn tại hoặc vòng lặp, span/event ID trùng, thiếu marker, event chưa đọc được, acknowledgment đến sau snapshot và result bị truncate. Điều kiện chỉ áp dụng cho hợp đồng capture đã khai báo. Span bên ngoài instrumentation không được suy ra từ graph quan sát.

Pilot đã có marker và root span hoàn tất 4/4, parent graph hợp lệ 4/4 và Docker ↔ ES khớp 16/16. Collector 7A.1 không lưu cutoff có seal, delivery receipt hoặc từng ingest timestamp. Do đó không đo được ingestion lag, và ingestion settled chưa được xác nhận. Cross giữ 4 PARTIAL, Single giữ 4 UNKNOWN. Không có snapshot mới, không có thay đổi Context API, và không dùng ground truth trong completeness.
