# Exploratory readiness 7A.8R

Gate dữ liệu đạt. Gate chạy 7B.1 còn chờ phê duyệt operator riêng bind freeze index SHA-256, model snapshot chính xác, credential khả dụng trong môi trường chạy, nguồn giá và cost ceiling. Shell chưa thấy OPENAI_API_KEY, chỉ kiểm boolean và chưa kiểm hiệu lực provider. Chưa benchmark và chưa gọi API.

evaluation_plan.json khóa thứ tự của 20 calls với seed 782 và đổi thứ tự Single/Cross luân phiên theo cặp, 10 Single + 10 Cross, 0 retry. Cùng prompt rca-evidence-v1 đã pin hash, output schema ModelAnalysis, decoding mặc định SDK, input evidence cap 7.000 ASCII bytes và output cap 800 token. Không tools, không history hay provider storage. Trước chạy cần bind model snapshot không đổi và preflight token của toàn request riêng. Không dùng case để tune prompt. Plan ghi schema đầu ra và trường dữ liệu lưu, output ngoài freeze trong thư mục run mới. Lưu trạng thái missing/failure, latency/usage/cost nếu có và tách adjudication.

Gate dùng --authorization trỏ JSON do operator cấp với decision_source USER_OPERATOR_DECLARATION, status APPROVED, operator_id, evaluation_type CONTROLLED_EXPLORATORY_EVALUATION, freeze_index_sha256, max_calls 20, retries 0, model_snapshot, cost_ceiling_usd và price_source. Kiểm credentials chỉ từ biến môi trường. Công cụ offline không cấp quyền thực thi và không chạy model. Formal gate vẫn giữ nguyên.

```powershell
.\.venv\Scripts\python.exe -B -m tools.freeze_benchmark_7a8r
.\.venv\Scripts\python.exe -B -m tools.freeze_benchmark_7a8r --require-ready
```

Lệnh thứ hai trả exit 1 vì chưa đủ điều kiện 7B.1.
