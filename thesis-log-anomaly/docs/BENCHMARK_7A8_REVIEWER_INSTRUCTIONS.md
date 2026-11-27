# Hướng dẫn reviewer 7A.8

1. Operator chọn reviewer độc lập với người tạo và phê duyệt campaign, ghi reviewer_id thật, xác minh xung đột và cấp allowlist theo run. Key giữ ngoài repo.
2. Reviewer đọc taxonomy, grouping, overlap disclosure và ground_truth_evidence_audit.json. Mở reviewer_package/case-01.dossier.json đến case-10.dossier.json, đối chiếu source hash và event IDs, ghi lý do từng case.
3. Điền bản sao case-NN.decision.json. ACCEPT ánh xạ VERIFIED, REJECT ánh xạ REJECTED, insufficient evidence ánh xạ INCONCLUSIVE. Giữ dossier canonical tag, thêm event:<ID> đã đọc. VERIFIED cần ít nhất một event. Điền timestamp có timezone. Không tự động thay nhãn 7A.7.
4. CORRECT dùng case-NN.correction.json để nêu nhãn đề nghị, lý do và evidence trước. Importer hiện không nhận enum CORRECT hoặc trường candidate label. Operator trong lượt review riêng cần lập dossier dẫn xuất mới hash-bound, giữ source và correction refs; reviewer ký VERIFIED cho digest bản hiệu chỉnh nếu đồng ý. Không dùng form gốc để ghi đè.
5. Với 4 nhóm, điền grouping.decision.json bằng APPROVE/REJECT/INSUFFICIENT_EVIDENCE, lý do, evidence refs, reviewer_id, timestamp. Giữ digest. Chưa có importer xác thực grouping trong repo; operator cần lưu quyết định group có provenance và bước xác minh riêng trước khi lock. Không nhập file group qua importer run.
6. Lưu receipt mới ở thư mục reviewer riêng. Không chia sẻ dossiers/labels, decision hoặc bảng grouping với inference runner. Reviewer không cần truy cập LLM output trong giai đoạn này.

```powershell
# Điền $completedDecision, $reviewKeyPath, $signedDecision, $dossierPath,
# $reviewerAllowlistPath và $newReceipt bằng các file review thực.
.\.venv\Scripts\python.exe -B -m tools.import_review_7a3 --decision $completedDecision --sign-key-file $reviewKeyPath --output $signedDecision
.\.venv\Scripts\python.exe -B -m tools.import_review_7a3 --decision $signedDecision --dossier $dossierPath --allowlist $reviewerAllowlistPath --output $newReceipt
```

Không tạo chữ ký hoặc nhập quyết định trong 7A.8.
