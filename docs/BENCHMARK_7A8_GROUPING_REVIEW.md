# Bằng chứng grouping 7A.8

| Nhóm | Mechanism | Injection và edge | Evidence phân biệt |
|---|---|---|---|
| NC | Normal | Không fault, Order→User/Product | Hai dependency 200, Order 201 |
| G1 | Processing failure | Hook Order sau lookup và trước create | Dependency 200, processing log và Order 500 |
| G2 | Dependency timeout | Delay phía Product, deadline Order→Product | 2,0 s và 2,25 s; Order 504 rồi Product 200, đóng SERVER |
| G3 | Database connection failure | Request DSN của Order→PostgreSQL | Order 503, connection failure, DB healthy và readiness sau rollback |
| G4 | Dependency unavailable | Product unavailable ở edge Order→Product | Product 503 và Order 502 có span link; propagation là handling |

Mỗi nhóm hai repetition. Plan fingerprints pin code/Compose và audit đọc runtime/activation của từng execution. G2 và G4 cùng edge nhưng deadline và HTTP failure khác nhau. G4 còn chia sẻ mechanism với retry lịch sử. G1 và G3 cùng vị trí service nhưng lỗi stage và repository khác. Độc lập chưa xác minh vì cảnh báo overlap và chưa có quyết định của người đánh giá. Reviewer dùng bảng cùng artifact paths trong configuration_grouping_review.json và grouping.decision.json.
