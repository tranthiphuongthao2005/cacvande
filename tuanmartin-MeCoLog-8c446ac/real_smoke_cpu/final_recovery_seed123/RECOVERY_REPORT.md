# Recovery của final evaluation đã mở

Recovery của final_evaluation_locked_seed123 do NumPy JSON serialization failure. Đây là lần chạy phục hồi đã được phê duyệt. Protocol, checkpoint, scorer, ngưỡng, support sampling và dữ liệu vẫn theo lock SHA-256 308e29ba2c48ff92c4ea3230206c99194daeb1e85a5832088c5b635c8285c63b.

## Sự cố và kiểm toán

Runner trước gặp NumPy int32 khi ghi bộ đếm nhóm support vào JSON. Recovery giữ nguyên runner trước và thay đúng ba binding khi chạy gồm thư mục output, JSON writer và CSV writer. Writer chuyển scalar NumPy thành giá trị Python tương đương, biểu diễn array bằng list lồng nhau, và từ chối số không hữu hạn trước khi tạo file. Fixture không dùng dữ liệu final xác minh round-trip, kiểu bool, int64 lớn hơn 2^53, float32/64, cấu trúc lồng, ID/seed và CSV 2 hàng × 4 cột.

Preflight qua checksum protocol, scorer, checkpoint, code gốc, NPZ và lineage. Strict load đủ 32 tensor. Recovery ghi 40 lượt và 8.000 score/predictions từ 20 seed. Kiểm tra lại CSV xác nhận các metrics và confusion matrix, mỗi phương pháp dùng cùng support ID theo seed, query giữ đúng 200 ID, không overlap, threshold luôn 0, file và weights giữ nguyên. Không có fallback. Dấu vết sự cố cũ giữ nguyên checksum.

## Kết quả cuối

| Chỉ số trung bình qua seed | Single | Length-aware multi |
|---|---:|---:|
| Binary Precision | 0,9603 | 0,7347 |
| Binary Recall | 0,4900 | 0,8675 |
| Binary F1 | 0,6473 | 0,7897 |
| Macro Precision | 0,8079 | 0,7821 |
| Macro Recall | 0,7318 | 0,7630 |
| Macro F1 | 0,7152 | 0,7566 |
| ROC-AUC | 0,6104 | 0,9116 |
| AP | 0,7479 | 0,9363 |
| FPR | 0,0265 | 0,3415 |
| TN / FP / FN / TP trung bình | 97,35 / 2,65 / 51,00 / 49,00 | 65,85 / 34,15 / 13,25 / 86,75 |

Chênh lệch multi trừ single trung bình là +0,1424 Binary F1, +0,0414 Macro F1, +0,3012 ROC-AUC, +0,1884 AP, +0,3150 FPR và +0,3775 Recall. Binary F1, ROC-AUC, AP và Recall tăng ở 20/20 seed. Macro F1 tăng ở 11 và giảm ở 9 seed. FPR tăng ở 18, giảm ở một và bằng nhau ở một seed.

| Độ dài | Normal / Anomaly | Recall single → multi | FPR single → multi |
|---|---:|---:|---:|
| 2–4 | 0 / 49 | 100,00% → 100,00% | — |
| 5–19 | 71 / 3 | 0,00% → 28,33% | 3,73% → 32,96% |
| 20–29 | 23 / 40 | 0,00% → 80,88% | 0,00% → 34,57% |
| 30–50 | 6 / 8 | 0,00% → 56,88% | 0,00% → 46,67% |

Phân tích độ dài chạy sau các metrics chính. Nhóm 2–4 chỉ có Anomaly nên không tính ROC-AUC. Nhóm 5–19 có 3 Anomaly và nhóm 30–50 có 14 mẫu tổng cộng, nên các tỷ lệ theo nhóm có độ phân giải hạn chế. Phân vị score theo nhóm và seed được lưu trong final_length_analysis.json.

Xu hướng tăng Binary F1, Recall và ROC-AUC từ development giữ được trên final, nhưng FPR tăng 31,50 điểm phần trăm, lớn hơn 3,25 điểm trên development. Precision giảm từ 96,03% xuống 73,47% trên final cân bằng. Mức tăng FPR cho thấy rủi ro của operating point đã khóa khi chuyển split. Một lần final trên BGL → HDFS chưa đủ để tách ảnh hưởng của overfitting development khỏi khác biệt phân bố và thành phần support.

Encode mất 2,38 giây. Runner đo 3,80 giây gồm fixture, preflight và báo cáo chính, trước hậu kiểm của wrapper. Peak working set lúc ghi summary là 610,44 MiB. Lệnh PowerShell hoàn thành trong 7,47 giây gồm khởi động tiến trình và các bước kiểm tra.

Hai mươi seed dùng chung checkpoint và query pool cân bằng. SD, median và phân vị trong JSON là mô tả độ nhạy với support, không phải khoảng tin cậy tổng quát hóa. Không chỉnh ngưỡng hoặc chọn seed sau khi xem final.
