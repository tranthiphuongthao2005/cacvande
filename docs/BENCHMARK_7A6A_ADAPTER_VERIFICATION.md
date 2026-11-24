# Checklist adapter 7A.6A

Chỉ dùng fixture và bundle có sẵn trong kiểm tra này.

| Adapter hoặc slot | Kiểm fixture/hồ sơ | Cần trước đợt collection |
|---|---|---|
| Normal A, Processing A | HTTP, Order root, context pair, seal/receipt, cleanup và checksum từ pilot | Bind adapter/version, scope và output vào phê duyệt batch mới; thống nhất cutoff |
| Cascade A, Timeout A, Database A | Batch 01–03, ground-truth candidate, HTTP, caller/dependency hoặc repository evidence | Chuyển bảo vệ one-POST, deadline và rollback sang adapter cohort, kiểm lại cấp quyền |
| Retry A | Ba attempt Product 503 và exhausted outcome trong fixture | Chứng minh retry timestamps, policy và final outcome trong adapter giới hạn |
| Processing B | Fault sau validation, trước lookup, không upstream và không ghi Order | Nối fault scope vào Compose và kiểm readback, rollback |
| Cascade B | User 503 và Order failure, không Product call | Nối User overlay vào adapter giới hạn |
| Timeout B | User vượt deadline, không Product call | Nối User delay và kiểm timing/cutoff |
| Retry B | MockTransport connect refusal, không HTTP downstream | Thiết kế activation/recovery an toàn và provenance |
| Normal B, Database B, Unavailable A/B | Review schema và scope | Giải quyết workload mới, auth fixture hoặc topology/taxonomy trước khi đề xuất |

Mỗi adapter cần test activation đúng scope, preflight thiếu điều kiện thì 0 POST, cap một POST và no retry, timeout giữ partial evidence, cleanup trong ngân sách và postflight xóa scope. Kiểm khớp event ID/nội dung producer/Docker/ES, duplicate/late, flush/handoff, seal và receipt. Kiểm cùng trace, Single đúng Order projection, isolation và snapshot checksum. Nếu Filebeat handoff chưa xác minh thì giữ nguyên. Approval pilot cũ không cấp quyền cho cohort.

Reviewer validator dùng dossier dẫn xuất Processing A, kiểm binding canonical, event IDs, references, trạng thái chờ và form theo schema importer. Importer regression dùng fixture. Không cấp identity, signature hay quyết định thật.
