# 7B.1 — Kết quả kiểm chứng Gemini

**Trạng thái: tích hợp đạt kiểm thử offline; smoke thật BLOCKED.**

| Hạng mục | Kết quả |
| --- | --- |
| SDK | `google-genai==1.68.0`, Gemini Developer API |
| Model ứng viên | `gemini-3.1-flash-lite`, văn bản và structured output được Google công bố |
| Cấu hình key | Kiểm tra boolean trả false trong container LLM đang chạy, shell Codex và Windows User/Machine environment mà phiên này đọc được |
| Billing và quota thực tế | Chưa có bằng chứng trên đúng project trong AI Studio |
| Phê duyệt smoke | Chưa có ID, thời hạn và trace được duyệt |
| Gemini / OpenAI / evaluation calls | 0 / 0 / 0 |
| Chi phí API phát sinh | 0 USD |
| Test Gemini và LLM | 20 passed, dùng SDK thật với HTTP mock cho Gemini |
| Regression | 131 passed, 10 skipped, 3 cảnh báo deprecation |
| Compose | Validate cấu hình thành công, image runtime đang chạy chưa cập nhật |
| SHA-256 | 8/8 mục trong freeze manifest 7A.8R và 63/63 fingerprint MeCoLog khớp |

Adapter Gemini tái sử dụng prompt, schema và kiểm tra evidence. Kiểm thử xác nhận Single/Cross đúng phạm vi; request mang JSON Schema; lỗi quota, timeout và output không hợp lệ không kích hoạt retry; yêu cầu thứ ba bị chặn. Thử nghiệm với HTTP mock chưa xác nhận model nhận schema hoặc trả output hợp lệ trên API Google.

Các file triển khai gồm `app/llm_provider.py`, `app/llm_api.py`, `app/llm_analysis.py`, `compose.llm.yaml`, `requirements-llm.txt`, `requirements-dev.txt`, `.env.example` và `tests/test_gemini_provider.py`.

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_gemini_provider.py tests/test_llm.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m tools.audit_research
```

Điều kiện còn lại được ghi trong [hướng dẫn thiết lập](BENCHMARK_7B1_GEMINI_SETUP.md). Chỉ cần cung cấp xác nhận tier/quota đã che thông tin nhạy cảm và quyết định operator có phạm vi. API key được inject riêng vào runtime.

## Kiểm tra lại với project Dự án Gemini 2

Người vận hành xác nhận AI Studio hiển thị Free Tier cho project mới. Quota thực tế của model vẫn chưa được cung cấp. Kiểm tra boolean trả false trong phiên PowerShell do Codex chạy, Windows User/Machine và container LLM đang phục vụ. `/health` và `/ready` hiện cùng trả HTTP 200, nhưng `/ready` xác nhận provider `mock`. Cần recreate từ cửa sổ PowerShell đang giữ key mới.

Đã build image LLM mới. Kiểm tra image bằng container tạm tắt network xác nhận SDK `1.68.0`, `/health` HTTP 200 và `/ready` HTTP 503 khi Gemini chưa được cấp quyền. Container đang phục vụ vẫn giữ cấu hình cũ trong khi chờ inject key mới.

Kiểm thử provider chạy lại và đạt 20/20. Freeze manifest và fingerprint vẫn khớp 8/8 và 63/63. Chưa có trace riêng được rà soát để gửi ra ngoài. Google quy định dữ liệu nhạy cảm, bí mật hoặc cá nhân không được gửi qua dịch vụ miễn phí. [Điều khoản Gemini API](https://ai.google.dev/gemini-api/terms)

[Hồ sơ phê duyệt](BENCHMARK_7B1_GEMINI_SMOKE_APPROVAL_DRAFT.md) ở trạng thái pending. Gemini, OpenAI và evaluation đều có 0 call. Structured output, evidence, token usage và latency trên provider thật vẫn chờ smoke. 7B.2 chưa sẵn sàng.

## Thực thi có điều kiện theo gemini-smoke-7b1-001

Đã ghi [tuyên bố của operator và ledger](../experiments/gemini_smoke_7b1/gemini-smoke-7b1-001.json). Phạm vi operator là 24 giờ. Hồ sơ ghi thời điểm quan sát UTC đầu tiên vì phiên này không có metadata thời điểm gửi tin nhắn. Gate hiện hành chỉ nhận expiration còn tối đa một giờ. Cần dùng cửa sổ runtime ngắn hơn trong phạm vi phê duyệt 24 giờ, không thay đổi gate.

Cascade A acceptance `8cc314768cf9c12e300243a20669ad28` nằm ngoài 10 trace frozen. Hai snapshot khớp manifest và schema, Single là tập con Order của Cross, với 3 event UNKNOWN và 5 event PARTIAL. Payload gửi provider qua `prepare` chỉ giữ ID kỹ thuật, thời gian và trường log theo schema cùng allowlist nội dung; không có nhãn hoặc thông tin kích hoạt. Hai GET cục bộ trả HTTP 200 và payload hash khớp snapshot. Integrity đạt 8/8 frozen, 190/190 cohort, 95/95 acceptance, 88/88 historical và 63/63 MeCoLog.

Kết quả vẫn **BLOCKED**. Container đang chạy báo provider `mock`, thiếu `GEMINI_API_KEY` và SDK. Quota của Dự án Gemini 2 chưa có bằng chứng AI Studio. Ledger ghi 0 lượt gọi, 0 USD; chưa có output, token hoặc latency từ provider. Trạng thái 7B.2 chưa sẵn sàng.

## Sau khi operator recreate

Kiểm tra trực tiếp xác nhận container thấy key, SDK `1.68.0`, provider cấu hình Gemini và model `gemini-3.1-flash-lite`. External calls đang tắt, call cap 0, validation retries 0. `/health` HTTP 200 và `/ready` HTTP 503 `PROVIDER_NOT_CONFIGURED` đúng với gate đang đóng.

Đã lưu quota theo số liệu operator chép lại từ AI Studio (RPM 0/15, TPM 0/250000, RPD 0/500) cùng thời điểm ghi nhận UTC. Phiên này chỉ nhận tệp văn bản nên thời điểm chụp và ảnh gốc chưa được đối chiếu. Integrity kiểm tra lại đạt 8/8 frozen, 190/190 cohort, 95/95 acceptance, 88/88 historical, 63/63 MeCoLog. SHA-256 hai input snapshot khớp hồ sơ.

**BLOCKED ở bước kích hoạt.** PowerShell của Codex không kế thừa key. [Khối kích hoạt](BENCHMARK_7B1_GEMINI_SETUP.md#phê-duyệt-gemini-smoke-7b1-001) ghi hai mốc UTC khi operator khởi chạy, không gửi POST. Ledger vẫn ghi 0 Gemini, 0 OpenAI, 0 evaluation calls và 0 USD. Runtime vẫn an toàn ở trạng thái external tắt. 7B.2 chưa sẵn sàng.

## Kết quả sau kích hoạt

Approval còn hiệu lực khi preflight. Container có SDK 1.68.0, Gemini đúng model, cap 2, còn 2, validation retry 0 và restart count 0. GET Context Single Order trả HTTP 504, nên không thể đối chiếu payload runtime trước khi gửi và dừng trước POST. [Ledger](../experiments/gemini_smoke_7b1/gemini-smoke-7b1-001.execution.json) ghi 0 generation, 0 USD và không có output.

Đã dừng riêng LLM, xác minh container exited và cổng 8016 từ chối kết nối. Cấu hình disabled chưa được áp dụng lại cho một runtime đang chạy. Không khởi động lại container đã kích hoạt. Integrity postflight đạt 8 frozen, 190 cohort, 95 acceptance, 88 historical và 63 MeCoLog. Trạng thái `BLOCKED_CONTEXT_PREFLIGHT`, 7B.2 chưa sẵn sàng.

## Kiểm tra ổn định sau HTTP 504

**CONTEXT_PREFLIGHT_PASS_WAITING_NEW_APPROVAL.** Context health và readiness HTTP 200. Elasticsearch healthy và cluster green, health probe mất 12,2 ms. Truy vấn đọc Elasticsearch theo trace từ Context trả HTTP 200. Order 3 hits, 113,91 ms đầu cuối, Elasticsearch took 38 ms. Cross 5 hits, 14,54 ms đầu cuối, took 7 ms.

HTTP 504 của lượt 001 được trả tại Context API. Code có hai đường trả 504, transport timeout khi gọi Elasticsearch hoặc tìm kiếm chưa hoàn tất và không có rows. Ledger cũ thiếu mã lỗi JSON, log Context chỉ có startup/shutdown. Timeout HTTP client của Context là 2.500 ms mỗi thao tác Elasticsearch, gồm PIT/search. Không xác định được thao tác cụ thể hoặc nguyên nhân gốc của lần trước. Contention là giả thuyết, chưa có đo trước/sau cùng workload để quy kết.

| Mode | HTTP 200 | Events / completeness | Min / median / max (ms) | Khoảng cách từ max đến mốc 2.500 ms |
| --- | --- | --- | --- | --- |
| Single Order | 5/5 | 3 / UNKNOWN | 60,011 / 69,508 / 466,176 | 2.033,824 ms |
| Cross | 5/5 | 5 / PARTIAL | 54,246 / 63,577 / 77,939 | 2.422,061 ms |

10/10 event sets và hash payload khớp snapshot từng mode. Mốc 2.500 ms là tham chiếu tương đối vì các số trong bảng đo toàn bộ Context request. [Chi tiết từng lượt](../experiments/gemini_smoke_7b1/context-stability-002.json)

Autoscale demo theo snapshot operator dùng 267,64% CPU, 2,189 GiB và 657 PIDs. Nó đã exited lúc 15:58:11 UTC trước khi kiểm tra. Lần đo đầu của phiên này ghi Elasticsearch 4,31% / 386,7 MiB, Context 0,20% / 21,15 MiB và LLM 21,30% / 40,03 MiB. Lần đo sau ghi lần lượt 0,83% / 392,4 MiB, 0,16% / 25,85 MiB và 0,21% / 40,41 MiB. Không stop/restart container nào trong phiên này. Giữ nguyên tài nguyên trong lúc chờ smoke. Sau smoke và khi operator xác nhận cần chạy lại demo, khôi phục riêng bằng `docker start autoscale-demo-control-plane`.

Integrity đạt 8/8 frozen, 190/190 cohort, 95/95 acceptance, 88/88 historical và 63/63 MeCoLog. LLM vẫn healthy với external tắt và cap 0. 0 Gemini, 0 OpenAI, 0 evaluation calls, 0 USD. [Approval 002](../experiments/gemini_smoke_7b1/gemini-smoke-7b1-002.json) chờ operator và quota mới. Không tái sử dụng 001.

## Smoke thật theo approval 002

**FAILED_SMOKE.** Activation còn hiệu lực, container chưa restart, quota theo xác nhận operator và ngân sách payload đạt. Context preflight trả HTTP 200 ở cả hai mode, đúng 3 event UNKNOWN và 5 event PARTIAL. Event IDs và payload SHA-256 khớp snapshot.

Single Order gửi một POST lúc 16:19:09 UTC. LLM Analysis Service trả HTTP 502 `PROVIDER_ERROR` sau 3.050,665 ms. Runtime giảm từ 2 lượt còn 1, xác nhận một lượt được tính vào cap. Adapter không trả upstream status hoặc nội dung lỗi, nên chưa xác định được Google đã nhận hay xử lý request. Không có structured response, token usage, returned model, response ID hoặc finish reason. Cross chưa gửi. Retry 0, OpenAI calls 0, evaluation calls 0. Ước tính Free Tier 0 USD, chưa đối chiếu hóa đơn.

Cleanup PASS theo phương án dừng riêng LLM. Docker xác nhận exited và cổng 8016 từ chối kết nối. Runtime với cấu hình disabled chưa được khôi phục. Autoscale demo không được khởi động lại. Approval 002 đã đóng, cấm tái sử dụng. Integrity postflight đạt 8/8 frozen, 190/190 cohort, 95/95 acceptance, 88/88 historical và 63/63 MeCoLog. 7B.2 chưa sẵn sàng.

Artifacts gồm [execution ledger](../experiments/gemini_smoke_7b1/gemini-smoke-7b1-002.execution.json), [results](../experiments/gemini_smoke_7b1/gemini-smoke-7b1-002.results.json) và [approval](../experiments/gemini_smoke_7b1/gemini-smoke-7b1-002.json).
