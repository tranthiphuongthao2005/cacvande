# Cohort audit 7A.8

Đọc kế hoạch, manifest, eligibility, grouping, governance, ledger, mười dossiers, bundles và snapshot export của 7A.7. SHA-256 kế hoạch 7bc63d44c6e1391a04606a1ed01a3a6ad1b703ebccb9cec7b74aabcd55dfb3cc khớp cùng fingerprint đã prelock. locked_at trước mốc consume đầu tiên và toàn bộ mười ledger tăng theo thứ tự plan. Ledger được collector ghi ngay trước POST. Mười request attempt đều 1, không thấy replay, mười campaign/run/trace/approval khác nhau.

190/190 cohort hash, 95/95 acceptance hash và 63/63 fingerprint MeCoLog khớp. Historical 17/20/21 batch, 33 pilot, 9 reviewer 7A.2, 4 mỗi smoke cũ, 15 Normal A smoke và 18 Processing pilot khớp. 42 event đối chiếu ở mỗi nguồn. Snapshot Pair/receipt hợp lệ, 20 snapshot SHA-256 riêng, inference export khớp bản source. So identity và snapshot digest với inventory cùng các file JSON/JSONL/CSV lịch sử trong experiments. Không thấy acceptance/development trace, event hoặc snapshot reuse. Scope của kiểm lịch sử là artifact có sẵn, không phải access audit toàn stack.

Mọi postflight PASS với readiness 200, scope trống. Source capture bounded, Single UNKNOWN, Cross PARTIAL và FILEBEAT handoff UNCONFIRMED. Không nâng TRACE_COMPLETE. Không POST, fault activation hoặc OpenAI call trong 7A.8.
