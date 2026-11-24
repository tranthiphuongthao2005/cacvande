# Decision register 7A.5I

Mọi quyết định có decision_source ADVISOR_SIMULATION, authority NON_BINDING và actual_approval_status PENDING. Đây là ADVISOR_SIMULATED_APPROVAL để thiết kế. Quyền chạy và phê duyệt thật vẫn thuộc con người được chỉ định. Bản máy đọc được nằm ở experiments/benchmark_7a5/benchmark_candidates_7a5i/decision_register.json.

| decision_id | Quyết định | Lý do | Implementation readiness | Evidence required |
|---|---|---|---|---|
| taxonomy | Hai chiều mechanism và propagation/handling | Tách nguyên nhân với biểu hiện | Candidate JSON | Operator duyệt hash và mapping |
| protocol | Paired Cross−Single và feasibility mô tả | So cùng trace | Candidate JSON | Operator duyệt rubric và protocol khóa |
| feasibility | ≥8 fault pairs, ≥4 nhóm độc lập, ≥2 Normal | Ngưỡng độ phủ vận hành | Planner đếm preflight | Evidence độc lập, nhãn xác minh, denominator sau chấm |
| completeness | PARTIAL/UNKNOWN có điều kiện | Bảo toàn giới hạn capture | Planner báo từng cặp và phân bố | Chính sách chấp nhận và provenance |
| blind | Loại development và cách ly nhãn | Hạn chế leakage | Validator manifest hiện có | Split khóa và reviewer độc lập |
| budget | 17 cặp, 34 calls, 0 retry | Trần workload | Dry-run forecast | Credential, model và cost approval |
