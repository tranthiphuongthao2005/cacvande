# Readiness 7A.6D.1

Collection gate BLOCKED do thiếu approval thật. Không gửi POST nghiệp vụ, không bật fault, không gọi OpenAI. Không thay đổi code, config hoặc artifact lịch sử; chỉ thêm bốn báo cáo. Không restart dịch vụ.

Trước acceptance, cần bốn /ready ổn định, kiểm ES/Filebeat và PostgreSQL, fault/scope trống và không còn rollback marker. Kibana là UI, đánh giá riêng khi core ingestion và Context qua. Cần per-batch governance mới và readiness preflight ngay trước phiên. Không mở benchmark.

Core readiness đạt 12/12 GET trong ba vòng cuối, ES/Filebeat/PostgreSQL healthy, flags trống và không marker. Điều kiện collector đạt ở thời điểm đo; cần chạy lại preflight ngay trước acceptance do latency có lúc sát 4 giây. Kibana vẫn unhealthy và là blocker observability UI riêng. Nghiệm thu tổng thể có Kibana chưa đạt. Flaky Processing giữ INTERMITTENT_UNRESOLVED. Operator cần duyệt batch thật và điều phối tải để giữ readiness ổn định.

```powershell
foreach ($config in 'normal-a','processing-a','timeout-a','database-a','cascade-a') {
  .\.venv\Scripts\python.exe -B -m tools.collect_benchmark_7a6c --configuration $config
}
.\.venv\Scripts\python.exe -B -m tools.collection_readiness_7a6a --batch timeout-a --audit
```
