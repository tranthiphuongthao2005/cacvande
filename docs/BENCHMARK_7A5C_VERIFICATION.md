# Xác minh Normal A

Run c1dd2611896447fdac37d655993a17a3, trace dee4b0f6fff429a43f2801fa79ff775d. Một POST Order trả HTTP 201, 1094 ms. Một GET đọc Order fixture. Preflight Docker Compose 5.0.2, Docker VM 5,79 GiB, disk còn khoảng 58,47 GiB, cả ba DB healthy, ES đọc được và scope accounting trống trước khi arm. Không bật fault flag.

Bằng chứng gồm 1 Order SERVER root đã đóng, 2 Order CLIENT span, 2 dependency SERVER span, 4 parent links hợp lệ. User/Product 200 và Order 201. Producer, Docker và Elasticsearch cùng 3 event, nội dung đối chiếu khớp, thiếu/trùng/ngoài scope/late đều 0 trong cửa sổ quan sát. Flush FLUSHED ở cả ba service. Receipt MATCHED_CAPTURE và seal OBSERVED_CAPTURE_ONLY. Filebeat per-event handoff UNCONFIRMED.

Single Order có 1 event và UNKNOWN. Cross có 3 event và PARTIAL. Single khớp projection Order của Cross. Ground truth không nằm trong context. Postflight PASS với bốn readiness HTTP 200, fault và accounting scope được gỡ. Readiness từng app xác minh DB; Context readiness xác minh ES. Bản ghi Order lab do POST tạo vẫn được giữ, cleanup chỉ hoàn nguyên cấu hình Compose và không thêm POST.

15 hash của live bundle khớp. Audit sau smoke xác minh ba bundle lịch sử 17/20/21 hash và 63/63 fingerprint MeCoLog. Không thay protocol, taxonomy, status reviewer hoặc eligibility lịch sử.

Regression trên PostgreSQL cô lập đạt 101 test trong 58,01 giây với 3 cảnh báo deprecation. Sau thay đổi nhỏ ở bước giữ chỗ output và deadline trước POST, 15 test liên quan cùng dry-run chạy lại đều đạt. Live smoke đã chạy đúng một lần.

```powershell
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a5c --campaign normal-a
.\.venv\Scripts\python.exe -B -m tools.validate_7a5
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_benchmark_7a5c.py
```

Tái lập live chỉ khi được duyệt riêng, với --live --operator-confirmed --max-requests 1 và --output chỉ đến thư mục mới trong experiments/benchmark_7a5. Không dùng lại output hiện có.
