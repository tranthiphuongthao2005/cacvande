# Ground truth evidence review 7A.8

10/10 đủ evidence để reviewer xem xét. ground_truth_evidence_audit.json ghi từng run/trace, mechanism, service, handling, SHA-256, event IDs, activation/runtime và span/log. Tất cả giữ NEEDS_REVIEW / UNVERIFIED, không quan sát mâu thuẫn trong các trường kiểm. Handoff ACK end-to-end thiếu ở cả 10. Candidate nguyên nhân và service chỉ là giả thuyết cần review.

- Normal có 201, fault flags tắt và User/Product 200.
- Processing có hai lookup 200 rồi log order_processing_failed và Order 500. Vị trí trước INSERT dựa trên hook. Không có DB transaction audit độc lập.
- Timeout xác nhận config 2,0/2,25 giây, 504, Product 200 về muộn và SERVER span đóng.
- Database ghi database_unavailable và connection failure khi container DB healthy. Scope là request DSN. Không có dấu hiệu DB crash.
- Cascade ghi 503 phía Product rồi Order 502, event và span link nối hai phía. Handling Propagated.
