# Ma trận cấu hình 7A.6A

Cột trạng thái mô tả bằng chứng và khả năng chạy adapter. Trạng thái độc lập của cả 14 slot là UNVERIFIED. Có 10 slot fixture-verified. Hai slot có evidence từ adapter giới hạn hiện tại, ba slot có bằng chứng live lịch sử từ collector cũ.

| ID | Mechanism | Handling | Injection position | Edge | Retry | HTTP dự kiến | Evidence | Trạng thái |
|---|---|---|---|---|---|---|---|---|
| normal-a | normal | local/none | Order POST; standard lookups | Order→User/Product | baseline | 201 | healthy dependency calls, committed Order | CURRENT_LIVE |
| normal-b | normal | local/none | alternate workflow absent | TBD | TBD | TBD | genuinely different healthy dependency path | DESIGN_BLOCKED |
| unavailable-a | dependency_unavailable | local | Product GET 503 | direct Product | none | 503 | Product SERVER only | OUT_OF_SCOPE |
| unavailable-b | dependency_unavailable | TBD | distinct causal topology needed | TBD | TBD | TBD | distinct root and Order pairing | OPERATOR_DECISION |
| processing-a | processing_failure | local | after lookup, before create | Order→User/Product | 1 per dependency | 500 order_processing_error | two healthy lookups; processing log and Order root | CURRENT_LIVE |
| processing-b | processing_failure | local | before dependency lookup | Order only | no lookup | 500 order_processing_error | stage log; no upstream calls or create | MISSING_ADAPTER |
| retry-a | dependency_unavailable | retry_exhausted + propagated | Product GET 503 | Order→Product | 3 attempts | 502 dependency_unavailable | three timed attempt spans and final failure | LEGACY_ADAPTER |
| retry-b | dependency_unavailable | retry_exhausted + propagated | Product connection refusal | Order→Product | 3 attempts | 502 dependency_unavailable | transport errors without downstream HTTP status | MISSING_ADAPTER |
| cascade-a | dependency_unavailable | propagated | Product GET 503 | Order→Product | 1 attempt | 502 dependency_unavailable | Product 503 → Order 502 linked spans | HISTORICAL_LIVE |
| cascade-b | dependency_unavailable | propagated | User GET 503 | Order→User | 1 attempt | 502 dependency_unavailable | User 503, no Product call | MISSING_ADAPTER |
| timeout-a | dependency_timeout | propagated | Product delay beyond caller deadline | Order→Product | 1 attempt | 504 dependency_timeout | caller timeout plus Product delay/late outcome | HISTORICAL_LIVE |
| timeout-b | dependency_timeout | propagated | User delay beyond caller deadline | Order→User | 1 attempt | 504 dependency_timeout | User edge deadline; no Product call | MISSING_ADAPTER |
| database-a | database_connection_failure | local | unreachable Order request DSN; baseline DB healthy | Order→PostgreSQL | 1 per dependency | 503 database_unavailable | repository connection failure; independent DB health | HISTORICAL_LIVE |
| database-b | database_connection_failure | local | authentication rejected on reachable DB | Order→PostgreSQL | TBD | TBD | isolated role, SQLSTATE, server health | DESIGN_BLOCKED |

Normal A và Processing A được liên kết lần lượt với normal_a_integration_smoke và processing_a_development_pilot. Cascade A, Timeout A, Database A lần lượt đối chiếu Batch 01–03. Retry A có scenario legacy và fixture, thiếu evidence live theo gate collection mới. Processing B, Retry B, Cascade B và Timeout B thiếu adapter live giới hạn. Normal B và Database B thiếu đường thiết kế. Unavailable A trực tiếp ngoài phạm vi Order pair. Unavailable B chờ quyết định taxonomy hoặc topology.

Cascade và Retry Exhaustion mô tả handling trong các mẫu Product 503 hiện có. Trường hợp direct unavailable, Cascade A và Retry A cần giữ cùng nhóm liên hệ thay vì đếm như ba nguyên nhân độc lập. User edge khác Product edge, stage trước lookup khác stage sau lookup, nhưng cần provenance deployment/hook và kiểm near-duplicate để xác minh độc lập. Mỗi group cần dấu vết config digest, image, campaign, cơ chế, edge, retry và evidence phân biệt. Thay seed hoặc trace ID chỉ đổi execution.
