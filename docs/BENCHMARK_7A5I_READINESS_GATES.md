# Readiness gates và reviewer validator 7A.5I

Planner chỉ đọc JSON và trả kết quả ra stdout. Nếu không có hồ sơ thật, taxonomy/protocol, independent groups, VERIFIED ground truth, blind eligibility, snapshot integrity, model/credential/cost và fault adapter đều bị chặn. Call budget có thể đạt khi hiện chưa có cặp. Tool không cấp quyền chạy dù tất cả check đạt.

Dùng --manifest cho manifest đã khóa theo schema app.benchmark, --governance cho hồ sơ operator quản lý và --allowlist cho reviewer HMAC registry riêng. approvals.taxonomy/protocol cần authority OPERATOR, operator_id, actual_approval_status APPROVED, candidate_sha256 và evidence path/SHA-256. approvals.provider cần các trường chung, model_snapshot, manifest_sha256, credentials_attested, cost_ceiling_usd dương, call_cap 34 và retries 0. configurations[group] chứa independence và fault_adapter, mỗi record ràng buộc group và manifest_sha256. Evidence file nằm cùng vùng lưu trữ governance, hash kiểm toàn vẹn. Cơ chế này tin cậy danh tính và chain of custody do operator quản lý, không xác thực chữ ký operator hoặc gọi provider.

reviews[run_id] cần dossier, decision theo path/SHA-256 và danh sách campaign_creator_and_approver_ids. Dossier review tương thích importer, scope run/trace và ground_truth_sha256 canonical khớp manifest. Importer xác thực HMAC, reviewer theo allowlist đã cấp và event refs. Reviewer không được có trong danh sách người tạo/duyệt campaign. Không sử dụng file mẫu làm quyết định thật. Kiểm tra HMAC chỉ chứng minh quyền theo registry; phân công độc lập vẫn cần con người xác nhận.

--reviewer-packet kiểm dossier dẫn xuất Processing A, form trống, binding canonical với importer, SHA-256 nguồn, snapshots, event IDs và ground-truth isolation qua schema context. Không ký, không import verdict. Giữ UNVERIFIED/NEEDS_REVIEW.

Validator kiểm hash lock, event scope, exact pairing, label path, trùng event và campaign/template grouping trong manifest. Planner loại run/trace lịch sử đã liệt kê. Việc xét near-duplicate xuyên các bộ dữ liệu và chất lượng handoff vẫn yêu cầu curator và receipt review trước khi chấp nhận manifest. Coverage được báo bằng bảng đếm mechanism và tình trạng completeness của từng mode.

Dry-run hiện có 0 cặp fault, 0 cặp Normal, 0 nhóm độc lập xác minh và 0 model calls. Reviewer packet khớp 13 tham chiếu và 4 event. Regression PostgreSQL cô lập đạt 110 test trong 53,39 giây, có 3 cảnh báo deprecation. Ba test mục tiêu đạt khi chạy lại. Audit khớp 18 hash Processing A qua manifest nguồn, 15 hash Normal A, 17/20/21 hash các batch lịch sử và 63/63 fingerprint MeCoLog.
