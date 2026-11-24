# Kế hoạch campaign 7A.4

Collector tái sử dụng fault flags, accounting phía producer, source seal, đọc Docker và PIT ES. Batch mặc định chạy dry-run. Thực thi cần `--execute-lab` và output mới. Một batch có một request đo, một GET lấy tham chiếu lab, và các probe readiness tách riêng. Preflight kiểm Docker VM, snapshot RAM của containers và readiness ba API cùng Context. Mốc điều phối 420 giây chặn gửi request đo muộn và dừng polling, với timeout riêng cho Compose và rollback. Không chạy song song với các tool đổi fault flags. Rollback về base/logging trong finally và kiểm lại readiness.

| Variant | Activation hiện có | Dấu hiệu cần đối chiếu | Biến thể có ý nghĩa về sau |
|---|---|---|---|
| Normal | Flags rỗng và Order hợp lệ | User/Product 200, Order 201, không lỗi dependency | Luồng đọc và cập nhật có dependency tự nhiên |
| Timeout | Product delay vượt timeout Order | Order 504 và lỗi timeout trong caller | Thay dependency hoặc delay trước/sau retry nếu bổ sung hỗ trợ |
| Unavailable | GET Product với fault unavailable | Product 503, log completion; ngoài scope Order-only | Fault availability tại dependency khác |
| Database | DSN request Order không kết nối | Order 503 và log database_connection_failed | Lỗi readiness, deadline DB hoặc dependency DB riêng |
| Processing | Order lỗi sau lookup | Order 500 và log order_processing_failed | Điểm lỗi khác trong processing có provenance |
| Retry exhaustion | Product unavailable, ba attempts | Ba lần thất bại gọi Product và Order 502 | Intermittent hoặc hồi phục có kiểm soát |
| Cascade | Product unavailable, một attempt | User 200, Product 503, caller failure và Order 502 | Path User → Order hoặc topology khác |

Từng nhánh xác minh runtime flags trong container khi bật fault, HTTP và telemetry. Nhánh Product trực tiếp có thể thu kỹ thuật nhưng không tạo Single Order. Retry, unavailable và cascade dùng chung cơ chế Product unavailable. Không đếm timestamp hoặc ID mới là cơ chế mới.

Batch đầu chỉ chọn Cascade để kiểm đường lan lỗi qua ba service. Dừng sau batch và chờ người vận hành. Trước đợt sau, phê duyệt theo quality gates và sức chứa VM, xác định cơ chế và workload đa dạng thực sự. Mức dry-run 14–28 và dự trù 42–84 trace ở thiết kế 7A chỉ là kế hoạch. Tính quy mô chính thức theo độ rộng CI mong muốn trên nhóm độc lập và chi phí hai lượt provider mỗi cặp, sau khi biết coverage và khả năng adjudication. 

```powershell
$stamp = Get-Date -Format yyyyMMdd_HHmmss
$out = ".\experiments\benchmark_7a4_$stamp"
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a4 --scenario cascade --output $out
.\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a4 --execute-lab --scenario cascade --output $out
```
