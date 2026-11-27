# Đề xuất batch collection 7A.6A

collection_proposal_7a6a.json là proposal chỉ đọc với 10 batch dự kiến. Ưu tiên Normal A / Processing A để chuẩn hóa bounded collection; sau đó xét Cascade A, Retry A, Timeout A và Database A; các slot thiếu adapter chỉ lên lịch sau khi qua checklist. Mỗi batch tham chiếu configuration ID và expected HTTP/evidence trong ma trận. Không tự kích hoạt batch hoặc gia hạn.

Mỗi batch trần 1 POST nghiệp vụ, 0 retry, 0 provider call. Trần lịch là 10 POST qua 10 phê duyệt riêng khi đủ điều kiện. Operator quyết định ngân sách tài nguyên/thời gian và endpoint scope theo adapter. Với Processing A, đề xuất tái dùng giới hạn 12 giây POST, 420 giây sau response cho snapshot và overall 792 giây từ pilot, nhưng cohort cần chốt mốc thực tế trước khi chạy.

Checklist batch gồm approval thực bind hash proposal/candidate, config ID, output mới, request cap, rollback và ngân sách; preflight; activation readback; capture và seal; Docker/ES reconcile; rollback baseline và postflight; snapshot pair; checksum và dossier. Timeout hoặc rollback lỗi thì giữ partial evidence, dừng batch. Không xóa volumes. Dossier riêng bàn giao reviewer độc lập. Cohort mới phải loại run smoke/pilot và review overlap trước khi chốt split.

Gate offline là điều kiện tiền kiểm của proposal. Luồng cohort live chưa triển khai; adapter pilot/legacy giữ phạm vi cũ và không dùng để vượt gate. Tích hợp gate vào entrypoint cohort và kiểm approval lần nữa ngay trước POST là điều kiện nghiệm thu. Không dùng điểm readiness benchmark LLM để cho phép collection, hay dùng approval collection để mở provider.
