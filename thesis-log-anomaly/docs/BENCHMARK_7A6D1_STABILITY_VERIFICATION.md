# Xác minh stability 7A.6D.1

Khoảng nghỉ 10 giây giữa các vòng. Mỗi GET host timeout 5 giây và bỏ qua proxy. 000 là không nhận HTTP status.

| Vòng khi kiểm toán còn chạy | User | Product | Order | Context |
|---|---|---|---|---|
| 1 | 200 / 4,242 s | 000 / 5,002 s | 000 / 5,002 s | 000 / 5,013 s |
| 2 | 200 / 2,081 s | 200 / 0,682 s | 200 / 0,198 s | 503 / 2,657 s |
| 3 | 200 / 0,074 s | 200 / 0,075 s | 200 / 0,041 s | 200 / 0,081 s |

Ba vòng sau khi PostgreSQL regression đã dừng, nghỉ 10 giây giữa các vòng.

| Vòng | User | Product | Order | Context |
|---|---|---|---|---|
| 1 | 200 / 1,290 s | 200 / 3,728 s | 200 / 2,087 s | 200 / 3,957 s |
| 2 | 200 / 1,151 s | 200 / 1,299 s | 200 / 1,187 s | 200 / 3,650 s |
| 3 | 200 / 0,135 s | 200 / 0,104 s | 200 / 0,248 s | 200 / 0,890 s |

12/12 host GET đạt. Filebeat trở về healthy, failing streak 0. ES và ba PostgreSQL healthy. Kibana vẫn unhealthy. Probe kết thúc khi Context 3,957 giây ở một vòng, sát timeout 4 giây của collector preflight, nên cần xác nhận lại trong cửa sổ launch.

Flaky Processing được lặp tuần tự 5 lần trên PostgreSQL lab cô lập, không dùng stack chạy thật. 5 PASS, 0 FAIL; thời gian pytest từng lượt 10,97 / 10,98 / 10,98 / 8,67 / 9,32 giây. Mốc lỗi 7A.6C cho thấy Product GET cuối cùng trả 200 nhưng quá muộn với deadline caller, nên Order trả 504 trước khi tới processing hook. Bằng chứng không chỉ ra lỗi logic processing. Resource contention, scheduling và độ trễ I/O là giả thuyết; chưa phân biệt được startup race hoặc network delay bằng trace hiện có. Giữ INTERMITTENT_UNRESOLVED. Không đổi timeout hay expected HTTP.

Regression 131 PASS, 0 FAIL, 3 cảnh báo deprecation, 72,24 giây. Checksum khớp 18 Processing A, 15 Normal A, 17/20/21 ba batch, 33 pilot, 9 review 7A.2 và 4 mỗi smoke cũ. 63/63 MeCoLog fingerprint khớp. Năm dry-run 0 POST. Fault flags/scopes ba app và Context trống; collection_runtime_lock không tồn tại.
