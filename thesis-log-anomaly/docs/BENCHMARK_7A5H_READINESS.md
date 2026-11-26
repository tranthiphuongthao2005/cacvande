# Điều kiện bàn giao 7A.5H

Hai đường kỹ thuật có evidence live là Normal A và Processing A trong smoke/development. Hiện 0 cấu hình độc lập VERIFIED, 0 nhãn VERIFIED và 0 run blind-eligible. Dossier dẫn xuất Processing A đã tương thích các trường importer, đang chờ phân công reviewer và quyết định thật.

Trước collection, operator duyệt taxonomy, scope cấu hình, chất lượng evidence, ngưỡng feasibility và ngân sách request. Cần kiểm nghiệm adapter fault còn thiếu, approval theo batch, preflight, activation, rollback, capture/snapshot cutoff và checksum. Chốt chính sách handoff UNCONFIRMED, nguồn chỉ OBSERVED_CAPTURE_ONLY và cách xử lý PARTIAL/UNKNOWN. Phải đăng ký grouping, isolation và kế hoạch split trước khi lấy ứng viên. Reviewer độc lập cần nhận dossier và bằng chứng cho candidate.

Trước real LLM benchmark cần đạt ngưỡng cohort đã duyệt, có ground truth và rubric adjudication, khóa protocol/snapshot/pairing/split, chứng minh no overlap và phân quyền label. Chốt model snapshot, prompt, decoding, token preflight, credentials, bảng giá và hard cap cả chiến dịch. Không hoạt động nào trong 7A.5H tự mở quyền collection hoặc inference. Hạn chế thực thi còn có khả năng thiếu cụm độc lập và thiếu ACK Filebeat.

Regression PostgreSQL cô lập đạt 107 pytest trong 57,77 giây, có ba cảnh báo deprecation. Kiểm tra mẫu reviewer và 13 tham chiếu SHA-256 đều đạt. Manifest cuối khớp 18 file Processing A, 15 file Normal A và 17/20/21 file ba batch lịch sử. MeCoLog khớp 63/63 fingerprint.

```powershell
.\.venv\Scripts\python.exe -B -m tools.validate_7a5d
.\.venv\Scripts\python.exe -B -m tools.audit_research
```
