# Reviewer workflow 7A.6B

Dùng dossier dẫn xuất Processing A trong processing_a_reviewer_handoff_7a5h. Reviewer-check kiểm SHA-256, hash canonical của form, 4 event IDs, pairing và label isolation. Operator phân công reviewer độc lập với campaign, xác minh danh tính ngoài tool và cấp allowlist riêng. Reviewer điền danh tính thật, timezone, quyết định, lý do và evidence refs, rồi ký bằng quy trình HUMAN_REVIEW_WORKFLOW.md.

Reviewer-import xác minh packet và gọi importer hiện có để kiểm HMAC, quyền theo run, identity và event refs cho VERIFIED. Ghi receipt xác thực bằng exclusive create vào thư mục khác với packet. Dossier nguồn, bản dẫn xuất và blank form giữ nguyên. Receipt không tự thay trạng thái label hoặc đưa pilot vào blind cohort. Thiếu identity hoặc thiếu evidence cho VERIFIED bị từ chối. Chỉ fixture và validation packet được dùng trong lượt này.

Operator cung cấp JSON campaign actors gồm run_id và creator_and_approver_ids. Importer từ chối thiếu roster hoặc reviewer trùng người tạo/duyệt campaign. Danh sách và danh tính thực vẫn cần operator xác minh ngoài tool. Fixture nhập receipt INCONCLUSIVE và từ chối ký nhận VERIFIED thiếu event ref. Không có quyết định thật được nhập.

```powershell
$packet = '.\experiments\benchmark_7a5\processing_a_reviewer_handoff_7a5h'
.\.venv\Scripts\python.exe -B -m tools.cohort_review_7a6b reviewer-check --packet $packet
# Sau khi reviewer thật ký quyết định và operator cấp registry
.\.venv\Scripts\python.exe -B -m tools.cohort_review_7a6b reviewer-import --packet $packet --signed $signedDecision --allowlist $reviewerRegistry --campaign-actors $campaignActors --output $newReceipt
```
