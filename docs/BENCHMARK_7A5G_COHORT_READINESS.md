# Cohort readiness 7A.5G

Hai cấu hình đã có bằng chứng live giới hạn gồm Normal A (integration smoke, HTTP 201) và Processing A (development pilot, HTTP 500 theo hook). 0 cấu hình độc lập VERIFIED. 0 ground truth VERIFIED. 0 run blind eligible. Matrix lịch sử và protocol giữ nguyên. Đường fixture khác vẫn cần nghiệm thu thực tế theo scope phê duyệt.

Trước benchmark, cần operator duyệt taxonomy, rubric, primary, policy incomplete và cohort ceiling; xác minh tính độc lập của cấu hình/campaign; nghiệm thu các adapter còn thiếu; chỉ định reviewer và duyệt dossier tương thích importer; khóa split và cặp snapshot từ run chưa lộ. Filebeat handoff vẫn UNCONFIRMED, cần duyệt giới hạn completeness. Model snapshot, decoding, token preflight, credentials và ngân sách cũng cần phê duyệt riêng trước đánh giá LLM. Hai pilot/smoke đã xem giữ ngoài blind set.

Offline checksums xác minh 15 file Normal A, 18 file Processing A theo manifest cuối, ba batch lịch sử 17/20/21, 33 pilot, 9 hồ sơ 7A.2 và hai smoke trước mỗi bộ 4. Fingerprint MeCoLog khớp 63/63.

Regression trên PostgreSQL cô lập đạt 107 pytest trong 64,74 giây, với 3 cảnh báo deprecation. Không gửi POST tới stack nghiệp vụ trong đợt kiểm toán.

```powershell
.\.venv\Scripts\python.exe -B -m tools.validate_7a5d
.\.venv\Scripts\python.exe -B -m tools.audit_research
```
