# Kiểm toán Processing A — 7A.5G

Run 77423da550654d5497ac8cc2a8d1ec41, trace 743b36700c9da51381cdb1889103ba69, campaign processing-a-development-pilot. Đọc 19 JSON, xác minh manifest cuối bao phủ đủ 18 file còn lại và manifest capture khớp 12 file. Digest của approval đúng scope khớp preflight. Dossier và snapshot digest khớp file tham chiếu.

Request attempt, reconciliation và pilot result đều ghi 1 measured POST. HTTP 500, order_processing_error, 797 ms. Trong code, requests=2 đếm GET Order fixture và POST Order; đây là trường tổng theo thiết kế collector, không phải access log độc lập. Health, Context, Elasticsearch và dependency calls nằm ngoài con số này. Code phát một POST, không có nhánh retry. Không có bằng chứng về POST thứ hai trong phạm vi collector; bundle không cung cấp access logs toàn stack.

Runtime bật processing chỉ tại Order. Product bật lab mode với fault rỗng. User không bật fault. Hai dependency SERVER 200 và hai Order CLIENT span liên kết với một Order SERVER root đã đóng. Log order_processing_failed xuất hiện sau hai lookup, sau đó Order ghi 500. Việc lỗi trước INSERT dựa vào vị trí hook trong code; bundle không chứa chứng từ giao dịch DB.

Producer/Docker/ES cuối 4/4/4, không có ID thiếu, thừa hoặc trùng. Producer seals, inspect, scope run/trace, digest envelope và receipt MATCHED_CAPTURE đã đối chiếu. Ba service FLUSHED và không có late event trong accounting inspection. Capture ES đầu tiên thiếu cả 4 event; receipt cuối khớp. Docker projection lưu trong bundle khớp trường nội dung ES và digest của cả 4 snapshot events khớp receipt. Producer hash dùng dòng Docker đầy đủ, trong khi bundle lưu projection đã bỏ trường và ghi JSON dạng chuẩn khác. Vì vậy có thể kiểm lại ID và các trường projected, còn phép so raw payload hash dựa trên kết quả đã ghi lúc live.

| Mốc UTC | Bằng chứng |
|---|---|
| 20:37:55.399579 | Activation check đã lưu |
| 20:37:56.194643 | File HTTP response được ghi, mốc xấp xỉ response |
| 20:37:58.555381 | Capture đầu được ghi, +2,361 s |
| 20:38:01.594890 | Seal cuối đóng |
| 20:38:07.057327 | Accounting inspection được ghi, +10,863 s |
| 20:38:30.376193 | Postflight được ghi, +34,182 s và khoảng 23,319 s sau capture accounting |
| 20:38:30.398499 | Receipt reconciliation timestamp sau cleanup |
| 20:44:56.852484 / 20:44:56.901739 | File Single / Cross được ghi, +420,658 / +420,707 s |

Metadata file phù hợp thứ tự capture → cleanup → snapshot và cửa sổ cutoff +420 đến +450 giây. Bundle không lưu đồng hồ monotonic hoặc mốc bắt đầu/kết thúc rollback chính xác. Khoảng thời gian trên là đối chiếu metadata, không phải phép đo độc lập của deadline. Postflight PASS, readiness User/Product/Order/Context đều 200, fault flags và accounting scope đều trống.

Single Order có 2 event UNKNOWN, đúng projection của Cross có 4 event PARTIAL. Cùng trace, scope hợp lệ và không lẫn các trường nhãn/injection. Log order_processing_failed là evidence quan sát được. Provenance hai mode khớp khi tính lại từ seal/receipt local. API provenance null. Handoff chưa xác minh, source coverage OBSERVED_CAPTURE_ONLY và TRACE_COMPLETE=false.
