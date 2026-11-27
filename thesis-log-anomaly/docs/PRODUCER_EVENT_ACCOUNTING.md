# Accounting phía producer

`EventIdentity` tạo UUID trước khi logger dispatch. Structured formatter phát cùng nội dung tới stderr của Docker và RotatingFileHandler NDJSON. Filebeat đọc glob NDJSON của từng service, xử lý parser và gửi vào Elasticsearch. Các điểm có thể mất event gồm lỗi format/write/flush, process crash, file rotate trước khi đọc, lỗi checkpoint registry hoặc index, cùng truncation/visibility ở query. Elasticsearch dùng event ID làm document ID, nên một lần ghi lại dùng cùng document ID có thể không để lại hai hit vật lý.

Overlay `compose.accounting.yaml` bật đúng một run ID, một trace ID. Producer dùng SQLite sidecar riêng trên log volume đã có, với tên ngoài glob Filebeat. Không đổi schema log hay ingress. Với scope được bật, event được append khi tạo UUID, cấp sequence theo service, ghi UTC timestamp và hash payload; hai handler ghi trạng thái độc lập. Các log khác tiếp tục qua handler cũ. SQLite transaction serialize các lần tạo event và đóng seal. Tổng hợp có expected IDs/count từ ledger producer, số flush thành công cả hai sink, số emission lỗi/chưa có đủ kết quả, status flush và version. Ledger local không chứng minh event chưa từng được tạo nếu process chết trước khi record sự kiện.

| Giai đoạn | Bằng chứng |
|---|---|
| EVENT_CREATED | Dòng SQLite trước khi dispatch, có ID và sequence |
| LOG_WRITE_ACCEPTED | Lệnh write trả về thành công. Trạng thái terminal LOG_FLUSHED hoặc FLUSH_FAILED đều chứng minh write đã trả về |
| LOG_FLUSHED | Cả write và flush của handler thành công. Không có fsync hoặc ACK đầu nhận |
| TRANSPORT_HANDOFF_CONFIRMED | Chưa có ACK per-event của Filebeat. Ledger giữ UNCONFIRMED |
| INGESTION_RECONCILED | Đọc lại Docker và ES, đối chiếu tập ID và nội dung qua scope seal |

Không dùng log marker chung đường truyền để xác nhận ACK. Seal và ledger nằm ở producer. Event tới sau giao dịch seal được cấp sequence kế tiếp và đánh dấu late; seal cũ bất biến. Tái kiểm tra ledger sau khi polling ES phát hiện late đến trước cutoff kiểm chứng.
