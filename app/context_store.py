"""Bounded Elasticsearch snapshots for cross-service investigation."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from time import monotonic, sleep

import httpx

from app.trace_store import EVENTS

FIELDS = (
    "@timestamp", "trace_id", "event_id", "span_id", "request_id", "service_name", "level",
    "message", "status_code", "dependency_service", "error_type", "endpoint", "http_method",
)
PAGE = 128
LIMIT = 512


@dataclass
class Snapshot:
    rows: list = field(default_factory=list)
    truncated: bool = False
    timed_out: bool = False
    polls: int = 1
    late_documents: bool = False


class ContextStore:
    def __init__(self, client):
        self.client = client

    def ready(self):
        response = self.client.post("/thesis-logs-*/_pit", params={"keep_alive": "15s"})
        pit = response.raise_for_status().json()["id"]
        self.close(pit)

    def close(self, pit):
        try:
            self.client.request("DELETE", "/_pit", json={"id": pit})
        except httpx.HTTPError:
            pass  # Elasticsearch expires the PIT.

    def snapshot(self, trace_id, service=None):
        response = self.client.post("/thesis-logs-*/_pit", params={"keep_alive": "15s"})
        if response.status_code == 404:
            return Snapshot()
        pit = response.raise_for_status().json()["id"]
        filters = [
            {"term": {"trace_id": trace_id}},
            {"bool": {"should": [{"match_phrase": {"message": code}} for code in EVENTS]
                      + [{"exists": {"field": "event_id"}}], "minimum_should_match": 1}},
            {"range": {"@timestamp": {"gte": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()}}},
        ]
        if service is not None:
            filters.append({"term": {"service_name": service}})
        body = {"query": {"bool": {"filter": filters}}, "_source": list(FIELDS),
                "sort": [{"@timestamp": "asc"}, {"event_id": "asc"}, {"_shard_doc": "asc"}],
                "track_total_hits": False, "pit": {"id": pit, "keep_alive": "15s"}}
        result = Snapshot()
        try:
            while len(result.rows) <= LIMIT:
                body["size"] = min(PAGE, LIMIT + 1 - len(result.rows))
                page = self.client.post("/_search", json=body, params={"allow_partial_search_results": "false"})
                data = page.raise_for_status().json()
                pit = data.get("pit_id", pit)
                body["pit"]["id"] = pit
                if data.get("timed_out") or data.get("_shards", {}).get("failed", 0):
                    result.timed_out = True
                hits = data["hits"]["hits"]
                result.rows.extend(hit.get("_source", {}) for hit in hits)
                if result.timed_out or len(hits) < body["size"]:
                    break
                body["search_after"] = hits[-1]["sort"]
        finally:
            self.close(pit)
        result.truncated = len(result.rows) > LIMIT
        result.rows = result.rows[:LIMIT]
        return result

    def fetch(self, trace_id, service=None, *, wait_ms=0):
        current = self.snapshot(trace_id, service)
        if not wait_ms or current.timed_out or current.truncated:
            return current
        deadline = monotonic() + wait_ms / 1000
        polls, changed = 1, False
        # Reopen the PIT so refreshes can expose newly ingested documents.
        while (remaining := deadline - monotonic()) > 0:
            sleep(min(.25, remaining))
            try:
                candidate = self.snapshot(trace_id, service)
            except httpx.TimeoutException:
                current.timed_out = True
                break
            polls += 1
            if candidate.timed_out:
                current.timed_out = True
                break
            changed |= candidate.rows != current.rows
            current = candidate
            if current.truncated:
                break
        current.polls, current.late_documents = polls, changed
        return current
