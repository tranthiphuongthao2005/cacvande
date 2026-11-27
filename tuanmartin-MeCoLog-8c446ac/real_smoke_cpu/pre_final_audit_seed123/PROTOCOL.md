# Đặc tả khóa trước final

## Toán học

Với encoder frozen fθ, biểu diễn của sequence i là zᵢ = normalize(fθ(xᵢ, pᵢ)), với chuẩn L2. Mỗi nhóm support S tạo centroid c(S) = normalize((1/|S|) Σᵢ∈S zᵢ). Audit yêu cầu embedding hữu hạn, có norm xấp xỉ 1, và kiểm tra trung bình trước chuẩn hóa hữu hạn, norm lớn hơn 10⁻¹². Dot product giữa hai vector đã chuẩn hóa là cosine similarity.

Cả hai phương pháp dùng c(N) từ cùng 10 support Normal. Baseline dùng một centroid c(A) trên toàn bộ 10 support Anomaly. Phương pháp hai prototype chia A thành Aₛ với true length ≤ 4 và Aₗ với true length > 4. Khi mỗi nhóm có ít nhất hai mẫu, dùng cả hai centroid. Khi nhóm nào có 0 hoặc 1 mẫu, dùng c(A) và ghi fallback. Score bằng maxⱼ(zq · c(Aⱼ)) − zq · c(N). Baseline có đúng một phần tử trong phép max. Dự đoán Anomaly khi score > 0, điểm bằng 0 cho Normal.

## Lấy support và sử dụng độ dài

Giữ thứ tự hàng đã khóa trong NPZ và manifest. Với từng seed từ 1000 đến 1019, khởi tạo NumPy default_rng (PCG64). Xáo trộn các chỉ số Normal trước, Anomaly sau, bằng cùng RNG của seed. Lấy 10 đầu của mỗi lớp và dùng đúng các ID đó cho cả hai phương pháp.

Ranh giới 4 event được hình thành từ chẩn đoán development và khóa trước final. Chỉ true length của support Anomaly, lấy từ lineage manifest, tham gia chia prototype. Query không cần một biến length riêng để định tuyến hoặc quyết định prototype. Encoder vẫn nhận sequence và tham số đã cắt/pad tới window 50 theo preprocessing đã khóa, nên thông tin độ dài có thể còn trong embedding.

## Hợp đồng đánh giá final

Ở lượt được phê duyệt, kiểm tra lock checksum, scorer, checkpoint, feature manifest, lineage và hash hai NPZ final trước khi nạp mảng. Encode support và query một lần, dùng cùng embedding query cho hai phương pháp và mọi seed. Nhãn query chỉ dùng ở bước tính metrics. Báo đầy đủ từng seed và các chênh lệch theo cặp, cùng số fallback. Không suy ra khoảng tin cậy tổng quát hóa từ 20 lần dùng chung query. Nếu integrity check, strict-load hoặc kiểm tra lineage thất bại, dừng trước khi báo metrics.

Audit hiện tại chỉ chạy trên development. Hai file NPZ final được băm ở dạng byte; các cột nhãn, feature và độ dài của final query không được dùng để tính toán hoặc chọn cấu hình.

## Chạy lại audit trên PowerShell

Chạy từ thư mục có model.py với một thư mục kết quả mới.

```powershell
$env:OMP_NUM_THREADS = '2'
$env:MKL_NUM_THREADS = '2'
.\.venv\Scripts\python.exe -B .\real_smoke_cpu\pre_final_audit.py `
  .\real_smoke_cpu\pre_final_audit_seed123_repeat
```
