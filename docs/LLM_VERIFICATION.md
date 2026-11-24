# Kiểm chứng giai đoạn 5

LLM Service chạy Compose tại 127.0.0.1:8016 ở chế độ mock. Dữ liệu lấy từ Context Service thật trên cùng trace cascade `09b71700f5dca84ec31f133b92b2ba91`. Trigger do verifier chọn trước. Hai lần POST cùng model mock, prompt `rca-evidence-v1` và config `rca-v1`. GET theo analysis ID trả đúng báo cáo đã sinh.

| Cấu hình | Scope thực tế | Event | Completeness | Status | Latency quan sát |
|---|---|---:|---|---|---:|
| LLM-Single | Order | 3 | UNKNOWN | INSUFFICIENT_EVIDENCE | 889,602 ms |
| LLM-Cross | User, Product, Order | 5 | PARTIAL | INSUFFICIENT_EVIDENCE | 67,961 ms |

Hai latency là phép đo từng request, gồm Context và quá trình xử lý. Thứ tự chạy Single trước Cross và khác trạng thái khởi động nên chưa có so sánh latency. Cả hai báo `CONTEXT_INCOMPLETE_DO_NOT_INFER_ABSENCE` và `CLAIM_SUPPORT_REQUIRES_HUMAN_REVIEW`. Token usage và estimated cost đều null vì mock. 0 lượt gọi OpenAI và không có chi phí API phát sinh. Model/key thật chưa cấu hình. Không có kết quả đánh giá chất lượng LLM.

Ví dụ JSON trích từ live mock:

```json
{
  "analysis_mode": "cross_service",
  "provider": "mock",
  "model_name": "mock-rca-v1",
  "prompt_version": "rca-evidence-v1",
  "context_completeness": "PARTIAL",
  "analysis_status": "INSUFFICIENT_EVIDENCE",
  "suspected_root_cause": null,
  "token_usage": null,
  "estimated_cost": null
}
```

Bản đầy đủ có ID, citations và kết quả hai mode tại [artifact kiểm chứng](../experiments/llm_mock_verification.json). Container dùng 40,41 MiB trên giới hạn 192 MiB và 0,23% CPU trong một lần lấy docker stats. Pytest đạt 40/40 trong 52,61 giây, gồm PostgreSQL lab riêng, với ba cảnh báo deprecation có sẵn. SDK 2.8.1 được kiểm tra trong container bằng HTTP transport fixture với structured request, parse output và token usage, không dùng OpenAI thật. Audit khớp 63 fingerprint. Detection trả 503 NOT_READY_FOR_SCORING.

## File

- Runtime: `app/llm_api.py`, `app/llm_analysis.py`, `app/llm_provider.py`.
- Compose và dependency: `compose.llm.yaml`, `services/llm/Dockerfile`, `requirements-llm.txt`.
- Kiểm tra: `tests/test_llm.py`, `tools/verify_llm.py`, `experiments/llm_mock_verification.json`. Cập nhật README và sáu tài liệu LLM.

Sau khi chạy [Compose ở chế độ mock](LLM_API.md), dùng đường dẫn artifact mới:

```powershell
$stamp = Get-Date -Format yyyyMMdd_HHmmss
.\.venv\Scripts\python.exe -B -m tools.verify_llm --output ".\experiments\llm_mock_$stamp.json"
.\.venv\Scripts\python.exe -B -m tools.audit_research
```

Nếu trace ví dụ hết retention, truyền `--trace-id` với trace cascade mới đã kiểm chứng. Giới hạn còn lại gồm OpenAI live chưa kiểm tra, kết quả lưu RAM, ngân sách gọi theo process, chưa có bảng giá được khóa và chưa có đánh giá nhân quả độc lập. Luồng chưa tích hợp workflow n8n.
