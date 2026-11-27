# Kế hoạch gated acceptance 7A.6D.2

Thứ tự Normal A → Processing A → Timeout A → Database A → Cascade A. Mỗi lượt cần một approval thực riêng, một POST tối đa và 0 retry. Chạy tuần tự, tránh chạy pytest đồng thời. Nếu gate, readiness, HTTP, reconciliation, rollback hoặc postflight lỗi, dừng cả chuỗi. Không chạy lại request thất bại.

Templates ở experiments/benchmark_7a5/acceptance_templates_7a6d2/. Mỗi file giữ PENDING, operator ID, evidence path/hash, approval ID và expiry để trống. Hash proposal và candidate đã ràng buộc. Operator cung cấp file thực riêng với evidence path tương đối so với file governance, SHA-256, operator identity, approval_id 32 hex thường duy nhất và expires_at có timezone. Đường dẫn output tương đối ghi trong approval phải khớp CLI và chưa tồn tại. Budget 792 giây theo CLI. Cohort DEVELOPMENT_ACCEPTANCE và blind_eligible=false được collector ghi vào kết quả.

| Cấu hình | Campaign | HTTP và evidence bắt buộc |
|---|---|---|
| normal-a | normal-a | 201, User/Product/Order telemetry, fault flags tắt |
| processing-a | processing-a-development-pilot | User/Product 200, Order 500 order_processing_error sau lookup và trước INSERT. 504 trước hook là FAIL |
| timeout-a | timeout-a-development-acceptance | Order 504 với timeout 2,0 s và Product delay 2,25 s, Product completion muộn và closed span trước seal |
| database-a | database-a-development-acceptance | Order 503 database_unavailable, DB container healthy, phục hồi request DSN và readiness |
| cascade-a | cascade-a-development-acceptance | Product 503 và Order 502, có span/log liên kết. Cơ chế dependency unavailable, handling propagated |

Từ thư mục thesis-log-anomaly, lệnh sau chỉ dành cho lúc operator đã cấp file thật tương ứng. Vòng lặp dừng tại batch đầu tiên thiếu file hoặc có exit code lỗi. Giữ default preflight timeout. Không thay file PENDING thành approval.

```powershell
$approvalRoot = 'C:\approvals\7a6d2'
foreach ($config in 'normal-a','processing-a','timeout-a','database-a','cascade-a') {
    $governance = Join-Path $approvalRoot "$config.approved.json"
    $output = ".\experiments\benchmark_7a5\accept_7a6d2_$($config.Replace('-', '_'))"
    if (!(Test-Path -LiteralPath $governance -PathType Leaf)) { throw "Missing operator approval for $config" }
    .\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a6c --configuration $config --live --governance $governance --output $output
    if ($LASTEXITCODE -ne 0) { throw "Acceptance stopped at $config" }
}
```

Collector kiểm readiness trước activation, scope ngay trước POST, ledger one-time và rollback trong finally. Evidence gồm producer/Docker/ES, receipt, mã HTTP, snapshot pair, manifest, dossier và postflight. Giữ UNKNOWN/PARTIAL, TRACE_COMPLETE=false và unconfirmed handoff khi chưa có evidence. Không đặt label trong context. Khi các lượt được duyệt kết thúc, kiểm lại readiness/flags/marker và chạy regression riêng với PostgreSQL lab cùng audit checksum.

Hồ sơ Normal A do local-project-operator khai báo nằm trong experiments/benchmark_7a5/normal_a_operator_governance_7a6d2. Sáu quyết định riêng là taxonomy, protocol, grouping, capture/completeness, adapter và batch. Gate có năm vị trí kiểm vì grouping/capture cùng một mục. Mỗi bằng chứng ghi USER_OPERATOR_DECLARATION. Lớp governance dùng decision_source OPERATOR theo enum runtime và trỏ SHA-256 tới bằng chứng. Schema kiểm scope, danh tính khai báo, expiry và digest. Không tạo hoặc khẳng định chữ ký hay phê duyệt giảng viên. Phạm vi live của lần này chỉ Normal A.
