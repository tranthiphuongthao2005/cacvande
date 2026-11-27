# Kết quả acceptance 7A.6D.2

Normal A PASS sau khi local-project-operator cung cấp đủ sáu quyết định và cả hai gate đều đạt. Preflight host ghi /ready HTTP 200 cho User/Product/Order/Context. Elasticsearch, Filebeat và ba PostgreSQL healthy. Collector kiểm lại runtime, fault flags và scope trước khi arm.

| Adapter | Trạng thái | POST | HTTP đo nghiệp vụ | Reconciliation / Single-Cross | Rollback / postflight |
|---|---|---:|---|---|---|
| Normal A | PASS | 1 | 201 trong 1.063 ms | 3/3/3; Single 1 UNKNOWN, Cross 3 PARTIAL | PASS, bốn readiness 200 |
| Processing A | PASS sau stability gate | 1 | 500 trong 234 ms | 4/4/4; Single 2 UNKNOWN, Cross 4 PARTIAL | PASS, bốn readiness 200 |
| Timeout A | PASS | 1 | 504 trong 2.157 ms | 5/5/5; Single 3 UNKNOWN, Cross 5 PARTIAL | PASS, bốn readiness 200 |
| Database A | PASS | 1 | 503 trong 140 ms | 4/4/4; Single 2 UNKNOWN, Cross 4 PARTIAL | PASS, bốn readiness 200 |
| Cascade A | PASS | 1 | 502 trong 141 ms | 5/5/5; Single 3 UNKNOWN, Cross 5 PARTIAL | PASS, bốn readiness 200 |

LIVE_VERIFIED 5/5, 5 POST trong toàn giai đoạn, 4 POST mới và 0 retry. Các bundle accept_7a6d2_* có 19/19 checksum mỗi lượt. Mọi run DEVELOPMENT_ACCEPTANCE, blind_eligible=false, dossier NEEDS_REVIEW và UNVERIFIED. Xem báo cáo tổng hợp để đối chiếu trace và runtime stabilization.
