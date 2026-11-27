# Protocol LLM-Single và LLM-Cross

Hai cấu hình dùng cùng trace, checkpoint model provider theo snapshot, prompt version, output schema, ngân sách, decoding mặc định và chính sách retry. Single chọn Order bằng quy tắc cố định; định nghĩa tập thử chính là các trace có Order và Context cross-service truy xuất được, khóa tập trước khi gửi provider. Báo riêng trace bị loại vì ngoài scope theo quy tắc này. Cross nhận các event cùng trace. Kết luận chỉ áp dụng cho phạm vi trace có Order.

Lưu trace ID, input event IDs, model/version, completeness, analysis status, latency, token usage, omitted events và validation warnings cho từng lần. Với đánh giá sau này, người chấm dùng nhãn và hồ sơ sự cố độc lập lưu ngoài API, chấm theo cặp về nguyên nhân nghi ngờ, evidence support, unsupported claims, mức bao phủ và abstention. Đảo thứ tự báo cáo khi chấm nếu có thể. Khóa rubric trước khi chạy. Báo chi phí theo bảng giá đã khóa nếu được phê duyệt. Không dùng một trace cascade để suy ra accuracy hoặc cấu hình nào tốt hơn.

Verifier mặc định chỉ chạy một cặp với mock và cùng trace cascade lấy từ Context thật. Không gửi batch provider thật.
