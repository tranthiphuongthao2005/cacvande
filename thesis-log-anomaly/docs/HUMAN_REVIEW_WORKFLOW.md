# Nhập quyết định reviewer

Reviewer được operator xác minh độc lập trước khi cấp quyền từng run. Reviewer mở dossier và bằng chứng gốc, kiểm cấu hình, HTTP, từng cạnh span, bằng chứng mâu thuẫn và khoảng trống. Chọn VERIFIED, REJECTED hoặc INCONCLUSIVE, ghi lý do và timestamp có timezone. Nếu chưa chấm, giữ form NEEDS_REVIEW của 7A.2. Không dùng output LLM làm nguồn nhãn.

Reviewer viết JSON với `run_id`, `reviewer_id`, `reviewed_at`, `decision`, `reviewed_evidence_references` và `justification`. Reference gồm `dossier:<canonical-sha256>` từ phiếu 7A.2 và `event:<event_id>` thuộc dossier. VERIFIED yêu cầu ít nhất một event đã xem. Signature HMAC-SHA256 xác thực channel theo shared key do operator cấp, tối thiểu 32 byte dưới dạng hex. Nó không chứng minh non-repudiation vì operator có shared secret. Key và allowlist chỉ lưu ngoài repo và bundle.

Allowlist JSON có dạng `{"reviewer-id":{"key_hex":"<64-hex-characters>","run_ids":["<run-id>"]}}`. Nạp vào output mới, không tự thay pilot sidecar. Dùng thư mục artifact reviewer có quyền truy cập giới hạn.

```powershell
.\.venv\Scripts\python.exe -B -m tools.import_review_7a3 --decision .\review-completed.json --sign-key-file $reviewerKeyPath --output .\review-signed.json
.\.venv\Scripts\python.exe -B -m tools.import_review_7a3 --decision .\review-signed.json --dossier $dossierPath --allowlist $operatorAllowlistPath --output .\review-imported.json
```

Output import là receipt quyết định do reviewer cung cấp. Operator kiểm chính sách adjudication và nguồn nhãn riêng trước khi tạo manifest đánh giá mới. Giai đoạn này không phát hành key reviewer, không điền phiếu và không nhập quyết định thật.
