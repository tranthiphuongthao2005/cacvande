# Kết quả collection 7A.7

Kế hoạch khóa trước POST và được gate kiểm theo SHA-256 `7bc63d44c6e1391a04606a1ed01a3a6ad1b703ebccb9cec7b74aabcd55dfb3cc`. Hoàn thành 10 slot theo thứ tự, 10 POST, 0 retry, không thay thế hoặc loại bỏ lượt nào. 8 fault và 2 Normal, mỗi cấu hình hai trace mới. 10 TECHNICALLY_VALID và 10 cặp Single/Cross, 10 reviewer dossiers NEEDS_REVIEW. Chưa có kết quả LLM.

| Repetition | Trace ID | HTTP | Producer / Docker / ES | Single / Cross | Hash |
|---|---|---:|---|---|---:|
| normal-a-r1 | `33a18e3bcbb3770cccb2fd265c3d558f` | 201 | 3 / 3 / 3 | 1 / 3 | 19/19 |
| normal-a-r2 | `f06659d95c6507b75eb0a87ddbff392d` | 201 | 3 / 3 / 3 | 1 / 3 | 19/19 |
| processing-a-r1 | `2c6cdbfd96c961845e8de9d9992e7b6c` | 500 | 4 / 4 / 4 | 2 / 4 | 19/19 |
| processing-a-r2 | `9253cc9ec0eac69e42208bc340942c69` | 500 | 4 / 4 / 4 | 2 / 4 | 19/19 |
| timeout-a-r1 | `ddc0fc6e6329639fcf1ff872cc963fb8` | 504 | 5 / 5 / 5 | 3 / 5 | 19/19 |
| timeout-a-r2 | `1371a475e726accb6eb78e66c8d60be4` | 504 | 5 / 5 / 5 | 3 / 5 | 19/19 |
| database-a-r1 | `4edfedcd68661d340a39fa095801d80c` | 503 | 4 / 4 / 4 | 2 / 4 | 19/19 |
| database-a-r2 | `bc13a751d11b8b4b3115753be0620a62` | 503 | 4 / 4 / 4 | 2 / 4 | 19/19 |
| cascade-a-r1 | `6317b3cfd046f6a225b6bb599b74a608` | 502 | 5 / 5 / 5 | 3 / 5 | 19/19 |
| cascade-a-r2 | `fcb8317f0f3ab06ce7a33b010f8b77b8` | 502 | 5 / 5 / 5 | 3 / 5 | 19/19 |

42 event riêng biệt khớp mỗi nguồn. Single 22 event tính trên 10 projection, Cross 42. Cả 10 rollback/postflight đều PASS và bốn HTTP 200 ở từng postflight. Single UNKNOWN và Cross PARTIAL, TRACE_COMPLETE=false, handoff UNCONFIRMED ở cả 10. Không xuất ground truth vào snapshot inference. Không trùng run ID, trace ID hoặc event ID trong cohort. Audit so trace/run với inventory lịch sử và acceptance, so event IDs với JSON/JSONL/CSV lịch sử trong experiments. Mười ledger record ràng buộc 10 approval riêng, không replay.

Integrity 190/190 checksum bundle mới, 95/95 acceptance, 63/63 fingerprint MeCoLog và checksums lịch sử khớp. Snapshot export khớp file SHA-256 trong manifest và đúng Order projection. 0 OpenAI call.

Regression sau khi collection dừng và container được khôi phục có 130 PASS, 1 FAIL và 3 cảnh báo deprecation trong 66,03 giây. Fixture test_fault_scenarios[processing] nhận 504 thay 500 do Product lookup timeout; Product GET cuối cùng trả 200 sau khoảng 2,154 giây. Đây là recurrence của lỗi intermittent đã ghi trước đó, riêng với 10 lượt live có evidence hợp lệ. Không sửa timeout hoặc kỳ vọng test. PostgreSQL test đã dừng.
