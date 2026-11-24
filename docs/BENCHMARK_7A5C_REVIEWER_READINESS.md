# Hàng đợi reviewer 7A.5C

| Run ID | Đánh giá evidence cho review | Còn thiếu |
|---|---|---|
| 1d3140d225414983ac361d14ed978220 | Có activation và chuỗi Product 503 → Order 502 | Candidate cause đang trống, cần adjudication và xác định cơ chế/propagation. Handoff ACK chưa có |
| 2ffef988d50840d5b59495263fd42c7d | Có activation, dependency timeout và Order 504, đủ để đưa giả thuyết cho reviewer | Review độc lập và Filebeat ACK |
| a3d1d1c17b614690a9154d7931161e8f | Có activation, lỗi kết nối DSN và Order 503, đủ để đưa giả thuyết connection failure | Review độc lập và Filebeat ACK. Giữ scope DSN |
| 1ce2bc12787e429e9627e3949f35d7e0 | Có bằng chứng Normal trong phạm vi quan sát | Source seal, ingestion ACK và reviewer |
| ce765c2fae7d44d8ac14372ac4941203 | Có bằng chứng Normal trong phạm vi quan sát | Source seal, ingestion ACK và reviewer |
| 4f37659b37694381bc2e61666632e079 | Có chuỗi 503 → 502 và giả thuyết nguyên nhân | Activation độc lập, source seal, ingestion ACK và reviewer |
| 70c9a115abfe487eacd82453dfd47aaa | Có chuỗi 503 → 502 và giả thuyết nguyên nhân | Activation độc lập, source seal, ingestion ACK và reviewer |

Sẵn sàng cho reviewer có nghĩa hồ sơ có evidence đủ để xem xét một giả thuyết có phạm vi. Handoff chưa xác minh hạn chế completeness. Không tự suy ra thiếu ACK làm mất mọi bằng chứng cơ chế. Cả 7 hồ sơ tiếp tục NEEDS_REVIEW. Hồ sơ pilot giữ vai trò development và không chuyển sang blind evaluation. Dùng các dossier/form đã liên kết trong reviewer_queue.csv và quy trình HUMAN_REVIEW_WORKFLOW.md.
