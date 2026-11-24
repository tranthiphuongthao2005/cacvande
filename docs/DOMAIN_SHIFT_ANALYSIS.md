# Phân tích domain shift

Ở giai đoạn 3, bộ chuyển đổi xây chuỗi từ service, event, level và HTTP status rồi đưa chuỗi vào tokenizer của cây Drain HDFS đã tái dựng. Cả 31 event đi qua nhánh fallback. Điều này có nghĩa là cây không match token của nội dung Microservices ở depth 4 và threshold 0,5. Nó khác với lỗi regex header của raw HDFS. Đường chẩn đoán đã bỏ qua bước tách header vì bản ghi JSON có field riêng.

| Nguồn chênh lệch | Bằng chứng hoặc hệ quả |
|---|---|
| Template chưa thấy | Các mẫu từ event có cấu trúc khác ngữ pháp và từ vựng của câu log HDFS. Catalog Microservices có thể nhận chúng mà không cần fit Drain. |
| Parser mismatch | Header Date/Time/Pid/Component và HDFS Content không tồn tại ở JSON Microservices. Cây HDFS tái dựng đúng trên 3.962 dòng training, nên replay đúng cây không làm JSON tương thích với cây đó. |
| Vocabulary mismatch | Vocabulary tham số fit từ BGL, tách riêng khỏi tập template và tokenizer SBERT. Gán lại ID hoặc tăng bảng file dù giữ kích thước có thể thay nghĩa của embedding. |
| Key OOV | `key:status` không có trong frozen key vocabulary. 29/29 key ở giai đoạn 3 là OOV. Status vẫn đi qua hàm chuẩn hóa số gốc. |
| Session length | Trace HTTP ngắn và phân nhánh. HDFS gom log theo BlockId, BGL theo window. Với window 50, giai đoạn 3 có 319/350 vị trí padding. |

Có thể thay parser, cách lập template, chính sách biểu diễn trường và cách nhóm trace để thử các phương án mà giữ nguyên checkpoint. Những thay đổi đó vẫn làm thay đổi phân bố đầu vào. Phương án positional `pos:1` giảm key OOV theo bảng gốc nhưng không cung cấp bằng chứng HTTP status tương đương vị trí đó ở miền huấn luyện. Không xây vocabulary mới trong giai đoạn này.

Encoder gốc dùng zero-padding và vẫn tính attention trên vị trí đệm. `p_type=0` cũng là NUM. Các phép chẩn đoán development trước đây cho thấy thay padding có thể thay embedding. Ở đây đo số vị trí đệm và độ dài thực tế. Chưa đo mức thay đổi score trên Microservices, vì chưa đủ điều kiện chạy scoring. Window 50 được giữ để so sánh shape. Các nghiên cứu khả năng bất biến theo chiều dài hoặc thích nghi hỗ trợ phải dùng development Microservices đã độc lập và cố định, ngoài HDFS final.
