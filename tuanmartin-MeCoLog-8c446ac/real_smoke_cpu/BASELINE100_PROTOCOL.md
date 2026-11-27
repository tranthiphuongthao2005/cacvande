# Protocol HDFS_v1 cho baseline BGL

Seed chia pool là 123. Dùng ground truth chính thức và thứ tự xáo trộn trong từng lớp, sau đó kiểm tra lineage trên toàn bộ HDFS.log. Pool support có 20 BlockId mỗi lớp, pool query có 100 mỗi lớp, cho cả development và final. Đây là lấy mẫu cân bằng để so sánh có kiểm soát, nên Precision và Average Precision phụ thuộc tỷ lệ lớp 50% trong tập con.

Loại toàn bộ 256 BlockId và các raw line của HDFS đã dùng trước đây. Loại ứng viên xuất hiện trên bất kỳ dòng nào có từ hai BlockId, kể cả khi BlockId thứ hai chưa được chọn. Kiểm tra giao đôi một của BlockId và số dòng trong bốn pool. Quy tắc này ngăn liên kết theo dòng log chung. Session vẫn có thể liên hệ qua thời gian, node hoặc cùng sự cố. Khi có metadata tương ứng, kiểm tra nhóm phụ thuộc trước khi diễn giải kết quả như bằng chứng tổng quát.

Khi đánh giá sau này, lấy support lồng nhau theo thứ tự manifest, khởi đầu 2, 5 và 10 mỗi lớp. Dùng nguyên một query pool khi đổi support size. Chỉ đưa nhãn support vào prototype. Nhãn query phục vụ chấm điểm. Dùng development để so sánh và khóa cấu hình trước khi mở final. Giữ ngưỡng cosine difference bằng 0. Script meta_test.py hiện chọn query từ phần còn lại của cùng NPZ, nên phép so sánh support size cần một entrypoint đánh giá tách biệt dùng các hàm gốc và cố định ID.

Pipeline đã fit cây Drain HDFS trên 204 session HDFS train cũ. Các session đó và 52 session test cũ đều bị loại khỏi pool mới. Vocabulary fit từ BGL train. Để tạo feature cho protocol mới, đề xuất tái tạo và đóng băng cây Drain từ đúng 204 HDFS train cũ rồi transform toàn bộ pool mới bằng cây cố định. Giữ vocabulary BGL, SBERT revision đã kiểm chứng và quy tắc tham số hiện tại. Kiểm tra lại lineage và mức truncation trước khi xuất. Không fit hoặc cập nhật từ development query hay final pools. Lượt baseline chỉ chốt ID, không xuất NPZ HDFS mới và không đánh giá HDFS.

## PowerShell

Chạy từ thư mục gốc có meta_train.py. Đổi tên output khi chạy lại để giữ kết quả cũ.

```powershell
$python = '.\.venv\Scripts\python.exe'
$env:OMP_NUM_THREADS = '2'
$env:MKL_NUM_THREADS = '2'
$env:MPLBACKEND = 'Agg'
$env:MPLCONFIGDIR = Join-Path (Resolve-Path .venv) 'matplotlib-cache'
$protocol = '.\real_smoke_cpu\hdfs_protocol_seed123.json'

& $python -B .\real_smoke_cpu\hdfs_protocol.py $protocol
if ($LASTEXITCODE -ne 0) { throw 'HDFS protocol failed' }
& $python -B .\real_smoke_cpu\baseline100.py .\real_smoke_cpu\baseline100_seed123 $protocol
if ($LASTEXITCODE -ne 0) { throw 'Baseline training failed' }
```

Wrapper baseline chạy meta_train.py gốc trên BGL_training.npz duy nhất. Kiểm tra APCL và gradient trước clipping từng episode. Ngân sách train là 120 giây và 1 GiB peak working set, được kiểm tra trong vòng lặp. Audit lưu đủ CLI, loss, gradient, checksum và strict-load. Checkpoint được chọn trước theo quy tắc lấy episode 100.
