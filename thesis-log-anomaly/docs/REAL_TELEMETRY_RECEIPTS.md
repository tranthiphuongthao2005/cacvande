# Telemetry receipt v1

Collector smoke gửi hai POST tạo fixture và đúng một POST Order đo thực tế trên localhost. Các fixture giữ trong DB lab; collector không xóa dữ liệu hoặc thay fault mode. Sau HTTP 201, collector thu log/span từ Docker stdout theo trace ID và ghi `source-seal-v1`. Seal chứa run ID, trace ID, source service, cutoff của lần đọc nguồn, trạng thái khép root span và event IDs đã quan sát. `expected_event_count=null` vì collector chưa có chứng cứ kiểm kê event tại producer hoặc exporter đã drain.

**Ba mốc khác nhau:** request đã trả response; log và span thấy được tại nguồn; capture quan sát đã đóng. State `OBSERVED_CAPTURE_ONLY` chỉ xác nhận mốc thứ ba trong phạm vi lần đọc. Nó không chứng minh mọi log đã được ghi trước cutoff. Không cấp source seal hồi tố cho pilot 7A.1.

`es-receipt-v1` dùng PIT chỉ đọc Elasticsearch, đối chiếu expected/observed ID, missing/unexpected/duplicate và fingerprint nội dung theo event. Poll có giới hạn, giữ mismatch làm lỗi chất lượng. MATCHED_CAPTURE là đã nhìn thấy đúng các event thuộc capture tại thời điểm đối chiếu. Không có ingest timestamp và ACK exporter nên không đo lag hay bảo đảm không còn event tới muộn. Bundle ràng buộc run/trace bằng schema và SHA-256. Receipt không phải watermark authoritative.

Smoke thật: [receipt, telemetry và snapshot](../experiments/benchmark_7a3_smoke/) · [checksum](../experiments/benchmark_7a3_smoke/checksum_manifest.json). Mỗi file dùng timestamp UTC. Application logging, OTel, Filebeat và ingest pipeline không có instrumentation mới; thay đổi chỉ nằm ở collector và Context v2.

```powershell
.\.venv\Scripts\python.exe -B -m tools.smoke_telemetry_7a3
$stamp = Get-Date -Format yyyyMMdd_HHmmss
.\.venv\Scripts\python.exe -B -m tools.smoke_telemetry_7a3 --execute-local --output ".\experiments\benchmark_7a3_smoke_$stamp"
```

Overlay demo trỏ tới bundle smoke đã kiểm chứng. Nếu chạy smoke mới, dùng bind source tương ứng và giữ nguyên bundle cũ.
