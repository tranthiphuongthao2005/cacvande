# Giới hạn 7A.8R

Mẫu nhỏ, prevalence fault 80% do thiết kế, 5 seen configurations, hai repetitions mỗi cấu hình và signature overlap. Reference labels dựa trên injection/runtime, chưa có independent review, nên diễn giải accuracy như mức khớp reference trong lab. Không dùng để tuyên bố unseen configuration, unseen mechanism hoặc generalization rộng.

Single UNKNOWN và Cross PARTIAL, TRACE_COMPLETE=false, Filebeat handoff UNCONFIRMED. Sự vắng mặt event không chứng minh sự kiện không xảy ra. Processing fixture giữ INTERMITTENT_UNRESOLVED, full regression ghi 130 PASS/1 FAIL từ 7A.7; không chạy lại trong lượt này. MeCoLog microservice scoring chưa được xác minh.
