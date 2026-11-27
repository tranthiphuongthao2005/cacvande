# Thu thập có kiểm soát

Giai đoạn 7A.1 dùng lại fault mode của Compose lab. Tool giữ các file lịch sử và ghi một bundle mới trong `experiments/`. Chạy mặc định là dry-run. Chế độ thực thi phải bật `--execute-lab`, chọn output chưa tồn tại và chỉ nhắm các API localhost cố định. Tối đa tám request đo mỗi batch, tối đa ba lần lặp mỗi scenario, chạy tuần tự. Mốc mặc định 420 giây chặn việc bắt đầu scenario hoặc request mới; các request đang chạy, thao tác restore và health probe có timeout riêng. Compose thay Product/Order tạm thời và restore trong finally khi có lỗi hoặc ngắt mềm. Dừng cứng tiến trình có thể làm mất bước restore. Không thu song song với công cụ khác đang đổi fault config.

Hỗ trợ bảy scenario hiện có: Normal, Timeout Product, Product unavailable, database failure ở Order, processing failure ở Order, retry exhaustion khi Product lỗi, và cascade Product → Order. Thực thi qua request thật. Timeout có delay Product theo cohort, retry và cascade có số attempt khác nhau. Thay đổi quantity, thứ tự tạo fixture và khoảng nghỉ chỉ là biến thiên workload. Di chuyển fault sang User, recovery giữa chừng hoặc thu ở concurrency cao cần thiết kế instrumentation và load-safety riêng. Chưa triển khai các biến thể đó. Pilot chọn **Normal và Cascade**, mỗi loại hai request nhằm kiểm thử một luồng thành công và một luồng lan truyền lỗi với ba service.

Mỗi run giữ trace và run ID, campaign, fault/workload ID và hash, dấu thời gian UTC, source environment, fingerprint ứng dụng từ các file runtime/Compose và tham chiếu telemetry/nhãn. Không lưu raw request body, email, khóa hoặc UUID của fixture. Không xóa volume hay tự dọn dữ liệu fixture khỏi app DB. Đọc Context thật và đối chiếu Docker trên cùng trace. Chỉ tạo Single nếu có Order. Case chỉ gọi Product có thể thu để audit và nằm ngoài tập so sánh Single–Cross. Không gọi OpenAI, LLM Service, Detection scoring hoặc n8n.

```powershell
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a1
$stamp = Get-Date -Format yyyyMMdd_HHmmss
$out = ".\experiments\benchmark_7a1_pilot_$stamp"
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a1 --execute-lab --output $out --scenario normal --scenario cascade --repetitions 2 --seed 124
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a1 --validate "$out\run_manifest.json" --similarity-output ".\experiments\benchmark_similarity_$stamp.json"
```

Nếu bị dừng cứng trong fault mode, dùng base và logging overlay để trả Product/Order về cấu hình thường trước khi chạy lại. Tiếp tục bảo toàn bundle đã thu. Chỉ chạy collector khi ELK, Context, Docker Desktop và các API lab hoạt động.
