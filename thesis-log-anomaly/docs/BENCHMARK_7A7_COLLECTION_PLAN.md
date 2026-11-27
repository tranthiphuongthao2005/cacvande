# Kế hoạch thu cohort 7A.7

Kế hoạch khóa trước POST tại experiments/benchmark_7a7/collection_plan.json và collection_plan.sha256. Cohort 7a7-evaluation-candidates-v1, thứ tự Normal A, Processing A, Timeout A, Database A, Cascade A, mỗi cấu hình hai repetition liền nhau. Tối đa 10 POST, 1 POST mỗi batch, 0 retry, tuần tự. 8 trace lỗi, 2 Normal và 20 lượt LLM là mục tiêu thiết kế, chưa phải quan sát. Lượt này có 0 OpenAI call.

Mỗi slot có campaign, repetition, configuration, output riêng, operator local-project-operator đã khai báo và expiry. Dùng shared gate, one-time ledger và các adapter A hiện có. Gate kiểm SHA kế hoạch và các fingerprint code/Compose trước activation lẫn ngay trước POST. Shared collector giữ timeout hiện hành và snapshot cutoff 420 giây sau response. Dừng tại batch lỗi, giữ evidence, không thay thế run.

Chỉ nhận EVALUATION_CANDIDATE, chưa blind-eligible. Cùng trace, Single phải đúng Order projection của Cross, dùng source receipt và SHA-256 cùng quy tắc scope. Context export chỉ chứa quan sát đã qua schema/isolation. Dossier, activation, governance và labels lưu riêng. Giữ UNKNOWN/PARTIAL và UNCONFIRMED theo bằng chứng. Không sửa lịch sử hoặc thay fault mechanisms.
