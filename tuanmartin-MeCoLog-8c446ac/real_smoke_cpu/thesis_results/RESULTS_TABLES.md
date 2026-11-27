# Bảng kết quả chính

| Chỉ số | Phương pháp | Development mean ± SD | Final mean ± SD | Δ Final Multi − Single | Seed cải thiện | Ghi chú |
|---|---|---:|---:|---:|---:|---|
| Binary Precision | Single-Prototype | 0,7486 ± 0,1498 | 0,9603 ± 0,0971 | — | — | Tham chiếu |
| Binary Precision | Length-Aware Multi-Prototype | 0,7874 ± 0,0579 | 0,7347 ± 0,1290 | -0,2256 | 2/20 | Tăng là cải thiện |
| Binary Recall | Single-Prototype | 0,3615 ± 0,0067 | 0,4900 ± 0,0000 | — | — | Tham chiếu |
| Binary Recall | Length-Aware Multi-Prototype | 0,6215 ± 0,0483 | 0,8675 ± 0,0852 | 0,3775 | 20/20 | Tăng là cải thiện |
| Binary F1 | Single-Prototype | 0,4837 ± 0,0271 | 0,6473 ± 0,0256 | — | — | Tham chiếu |
| Binary F1 | Length-Aware Multi-Prototype | 0,6935 ± 0,0446 | 0,7897 ± 0,0891 | 0,1424 | 20/20 | Tăng là cải thiện |
| Macro F1 | Single-Prototype | 0,5860 ± 0,0343 | 0,7152 ± 0,0295 | — | — | Tham chiếu |
| Macro F1 | Length-Aware Multi-Prototype | 0,7224 ± 0,0383 | 0,7566 ± 0,1155 | 0,0414 | 11/20 | Tăng là cải thiện |
| ROC-AUC | Single-Prototype | 0,4733 ± 0,0411 | 0,6104 ± 0,0279 | — | — | Tham chiếu |
| ROC-AUC | Length-Aware Multi-Prototype | 0,8732 ± 0,0397 | 0,9116 ± 0,0444 | 0,3012 | 20/20 | Tăng là cải thiện |
| Average Precision | Single-Prototype | 0,6491 ± 0,0215 | 0,7479 ± 0,0155 | — | — | Tham chiếu |
| Average Precision | Length-Aware Multi-Prototype | 0,8724 ± 0,0276 | 0,9363 ± 0,0293 | 0,1884 | 20/20 | Tăng là cải thiện |
| FPR | Single-Prototype | 0,1375 ± 0,0835 | 0,0265 ± 0,0648 | — | — | Tham chiếu |
| FPR | Length-Aware Multi-Prototype | 0,1700 ± 0,0527 | 0,3415 ± 0,1924 | 0,3150 | 1/20 | Giảm là cải thiện |

Δ là chênh lệch ghép cặp trên final. FPR tăng 0,3150, tức 31,50 điểm phần trăm. Mỗi split gồm 20 seed, 40 lượt và 8.000 dự đoán. Không có fallback cho hai cấu hình đang so sánh.

Confusion matrix trung bình mỗi seed theo TN / FP / FN / TP.

- Single-Prototype: 97,35 / 2,65 / 51,00 / 49,00.
- Multi-Prototype: 65,85 / 34,15 / 13,25 / 86,75.

## Đối chiếu artifact

25/25 mục khớp.

| Kiểm tra | Kết quả |
|---|---|
| Protocol, recovery và sự cố | Khớp |
| Development seed và kích thước | Khớp |
| Development support hash theo cặp | Khớp |
| Development 200 query cố định, label, score và threshold | Khớp |
| Development confusion matrix, P/R/F1, AUC, AP và FPR tính lại | Khớp |
| Final seed và kích thước | Khớp |
| Final support hash theo cặp | Khớp |
| Final 200 query cố định, label, score và threshold | Khớp |
| Final confusion matrix, P/R/F1, AUC, AP và FPR tính lại | Khớp |
| Development khớp audit trước final | Khớp |
| Fallback, seed và ngưỡng | Khớp |
| Final thống kê single | Khớp |
| Development mean/SD single | Khớp |
| Final thống kê length_two | Khớp |
| Development mean/SD length_two | Khớp |
| Paired binary_f1 | Khớp |
| Paired macro_f1 | Khớp |
| Paired roc_auc | Khớp |
| Paired average_precision | Khớp |
| Paired fpr | Khớp |
| Paired binary_recall | Khớp |
| Recall/FPR và số mẫu nhóm 2-4 | Khớp |
| Recall/FPR và số mẫu nhóm 5-19 | Khớp |
| Recall/FPR và số mẫu nhóm 20-29 | Khớp |
| Recall/FPR và số mẫu nhóm 30-50 | Khớp |
