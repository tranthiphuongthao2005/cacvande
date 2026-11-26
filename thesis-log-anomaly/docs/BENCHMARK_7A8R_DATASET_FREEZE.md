# Dataset freeze 7A.8R

EXPLORATORY_DATASET_FROZEN. evaluation_manifest.json SHA-256 366545fd4bf53954c29f583b2eae5f6a9dc3c25da0a0437cc7fc1407cd1a7dd3. freeze_manifest.sha256 pin 8 file protocol, labels/audit, manifests, scoring, execution plan và limitations. Hash của index là 6f4e45bdbf11a6a26c6ec5210377366795208020d35066a2be5dc1b81fd36b49. Readiness report nằm ngoài freeze index vì phản ánh môi trường/approval thay đổi.

10/10 pair cùng trace và Single là Order projection của Cross. Snapshot cutoff theo contract 420 giây. Manifest inference chỉ có case ID và hai path/SHA-256. Scope, expected outcomes, activation và reference labels ngoài payload; raw context giữ observed HTTP và log. Kiểm snapshot theo artifact gốc và receipt qua audit 7A.8 trước freeze. Cohort history audit không thấy reuse, các checksums 190, 95, lịch sử và 63 fingerprint khớp.

Audit lịch sử 7A.8 hiện quét mọi JSON ngoài thư mục cohort và formal output. Sau khi thêm namespace exploratory, audit đó bắt gặp ID/hash được dẫn chiếu trong manifest mới và dừng. Đây là overlap do tài liệu dẫn xuất, không phải snapshot reuse trong historical bundle. Giữ nguyên formal scanner/gate. Gate exploratory xác minh source scope và digest riêng. Nếu chạy lại formal audit ở một lượt formal sau này, cần operator duyệt cách phân loại namespace dẫn xuất để scanner phân biệt tham chiếu với history.
