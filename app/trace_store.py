"""Read a bounded application-log snapshot and materialize DetectionSession v1."""

import hashlib
import re
from datetime import datetime, timedelta, timezone

import httpx

from app.contracts import DetectionSession, LogEvent

SERVICES = ("user", "product", "order")
EVENTS = ("request_completed", "request_failed", "database_connection_failed",
          "dependency_attempt_failed", "dependency_exhausted", "order_processing_failed")
FIELDS = ("@timestamp", "event_id", "trace_id", "service_name", "span_id", "level", "message",
          "status_code", "endpoint", "http_method")
MAX_EVENTS = 2048
PAGE_SIZE = 256


def valid_trace(trace_id):
    return bool(re.fullmatch(r"[0-9a-f]{32}", trace_id)) and trace_id != "0" * 32


class TraceStore:
    def __init__(self, client, environment="local"):
        self.client = client
        self.environment = environment

    def fetch(self, trace_id):
        if not valid_trace(trace_id):
            raise ValueError("Invalid trace ID")
        pit = self.client.post("/thesis-logs-*/_pit", params={"keep_alive": "30s"})
        if pit.status_code == 404:
            return None
        pit = pit.raise_for_status().json()["id"]
        body = {
            "size": PAGE_SIZE, "track_total_hits": False, "_source": list(FIELDS),
            "query": {"bool": {"filter": [
                {"term": {"trace_id": trace_id}}, {"exists": {"field": "event_id"}},
                {"terms": {"service_name": SERVICES}}, {"terms": {"message": EVENTS}},
                {"range": {"@timestamp": {
                    "gte": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()}}},
            ]}},
            "sort": [{"@timestamp": "asc"}, {"event_id": "asc"}, {"_shard_doc": "asc"}],
            "pit": {"id": pit, "keep_alive": "30s"},
        }
        rows, seen, scanned = [], {}, 0
        try:
            while scanned < 2 * MAX_EVENTS and len(rows) <= MAX_EVENTS:
                result = self.client.post("/_search", json=body).raise_for_status().json()
                pit = result.get("pit_id", pit)
                body["pit"]["id"] = pit
                if result.get("timed_out") or result.get("_shards", {}).get("failed", 0):
                    raise ValueError("Incomplete Elasticsearch response")
                hits = result["hits"]["hits"]
                for hit in hits:
                    row = hit["_source"]
                    if row["trace_id"] != trace_id:
                        raise ValueError("Unexpected trace returned")
                    event_id = row["event_id"]
                    if event_id in seen:
                        if seen[event_id] != row:
                            raise ValueError("Conflicting duplicate event")
                        continue
                    seen[event_id] = row
                    rows.append(row)
                scanned += len(hits)
                if len(hits) < PAGE_SIZE:
                    break
                body["search_after"] = hits[-1]["sort"]
        finally:
            try:
                self.client.request("DELETE", "/_pit", json={"id": pit})
            except httpx.HTTPError:
                pass  # PIT expires automatically.
        return self.session(trace_id, rows) if rows else None

    def session(self, trace_id, rows):
        events = sorted(
            (LogEvent(event_id=row["event_id"], timestamp=row["@timestamp"],
                      service_name=row["service_name"], span_id=row.get("span_id"),
                      level=row["level"], event_name=row["message"], message=row["message"],
                      http_status=row.get("status_code")) for row in rows),
            key=lambda event: (event.timestamp, event.event_id),
        )
        candidate_root = "order" if any(
            row["service_name"] == "order" and row["message"] == "request_completed"
            and row.get("endpoint") == "/orders" and row.get("http_method") == "POST"
            for row in rows
        ) else "unknown"
        kept = events[:MAX_EVENTS]
        identity = hashlib.sha256(f"trace-v1|{self.environment}|{trace_id}".encode()).hexdigest()
        return DetectionSession(
            session_id=identity, trace_id=trace_id, service_name=candidate_root,
            start_time=kept[0].timestamp, end_time=kept[-1].timestamp, events=kept,
            source_metadata={
                "collector": "elasticsearch", "environment": self.environment,
                "completeness": "partial", "dropped_events": len(events) - len(kept),
            },
        )
