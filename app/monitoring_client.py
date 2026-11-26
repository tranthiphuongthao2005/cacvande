"""Bounded, allowlisted HTTP access to Elasticsearch and Hybrid Detection."""

import asyncio
from datetime import datetime, timezone

import httpx
from pydantic import ValidationError

from app.context_store import FIELDS
from app.hybrid_detection import HybridResult

TRANSIENT = {408, 429, 502, 503, 504}
SLOW = {408, 504}


class PollFailure(Exception):
    pass


class DetectionFailure(Exception):
    def __init__(self, code, *, retryable=False, cooldown=False, result=None):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.cooldown = cooldown
        self.result = result


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


class ElasticsearchPoller:
    def __init__(self, client, settings):
        self.client = client
        self.settings = settings

    async def poll(self, lower, upper, persist, stopping):
        pit = None
        try:
            async with asyncio.timeout(self.settings.poll_timeout_seconds):
                response = await self.client.post(f"/{self.settings.es_index}/_pit",
                                                  params={"keep_alive": "30s", "allow_partial_search_results": "false"})
                pit = response.raise_for_status().json()["id"]
                if not isinstance(pit, str) or not pit:
                    pit = None
                    raise PollFailure("INVALID_PIT")
                query = {
                    "size": self.settings.batch_size, "track_total_hits": False,
                    "_source": list(FIELDS),
                    "query": {"range": {"@timestamp": {"gte": iso(lower), "lt": iso(upper)}}},
                    "sort": [{"@timestamp": {"order": "asc", "format": "strict_date_optional_time_nanos"}},
                             {"event_id": {"order": "asc", "missing": "_last"}}, {"_shard_doc": "asc"}],
                }
                for _ in range(self.settings.max_pages):
                    if stopping.is_set():
                        return False
                    query["pit"] = {"id": pit, "keep_alive": "30s"}
                    response = await self.client.post("/_search", json=query,
                                                      params={"allow_partial_search_results": "false"})
                    data = response.raise_for_status().json()
                    next_pit = data.get("pit_id", pit)
                    if not isinstance(next_pit, str) or not next_pit:
                        raise PollFailure("INVALID_PIT")
                    pit = next_pit
                    if data.get("timed_out") or data.get("_shards", {}).get("failed"):
                        raise PollFailure("INCOMPLETE_SEARCH")
                    hits = data["hits"]["hits"]
                    if not isinstance(hits, list) or len(hits) > self.settings.batch_size:
                        raise PollFailure("INVALID_SEARCH_RESPONSE")
                    cursor = hits[-1]["sort"] if hits else None
                    if hits and (not isinstance(cursor, list) or len(cursor) != 3 or cursor == query.get("search_after")):
                        raise PollFailure("INVALID_SEARCH_CURSOR")
                    persist(hits)
                    if len(hits) < self.settings.batch_size:
                        return True
                    query["search_after"] = cursor
                raise PollFailure("POLL_PAGE_LIMIT")
        except TimeoutError:
            raise PollFailure("ELASTICSEARCH_TIMEOUT") from None
        except httpx.TimeoutException:
            raise PollFailure("ELASTICSEARCH_TIMEOUT") from None
        except httpx.HTTPError:
            raise PollFailure("ELASTICSEARCH_UNAVAILABLE") from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise PollFailure("INVALID_SEARCH_RESPONSE") from None
        finally:
            if pit is not None:
                try:
                    async with asyncio.timeout(2):
                        (await self.client.request("DELETE", "/_pit", json={"id": pit})).raise_for_status()
                except (httpx.HTTPError, TimeoutError):
                    # The PIT also has a finite server-side lifetime.
                    pass


class DetectionClient:
    def __init__(self, client, timeout):
        self.client, self.timeout = client, timeout

    async def detect(self, trace_id):
        try:
            async with asyncio.timeout(self.timeout):
                response = await self.client.post("/detect/hybrid", json={"trace_id": trace_id, "mode": "AUTO"})
        except (TimeoutError, httpx.TimeoutException):
            raise DetectionFailure("DETECTION_TIMEOUT", retryable=True, cooldown=True) from None
        except httpx.TransportError:
            # A transport failure can occur after the server received the request.
            raise DetectionFailure("DETECTION_TRANSPORT_ERROR", retryable=True, cooldown=True) from None

        status = response.status_code
        try:
            output = HybridResult.model_validate_json(response.content, strict=True)
            self.validate(output, trace_id, status)
        except (ValidationError, ValueError):
            if status in TRANSIENT:
                raise DetectionFailure(f"DETECTION_HTTP_{status}", retryable=True, cooldown=status in SLOW) from None
            raise DetectionFailure("INVALID_DETECTION_RESPONSE") from None
        if output.detection_status == "DETECTION_ERROR":
            raise DetectionFailure(f"DETECTION_HTTP_{status}" if status != 200 else "DETECTION_ERROR",
                                   retryable=status in TRANSIENT, cooldown=status in SLOW, result=output)
        return output

    @staticmethod
    def validate(output, trace_id, status):
        decision = {"ANOMALY": True, "NO_ANOMALY_DETECTED": False}.get(output.detection_status)
        evidence = set(output.evidence_event_ids)
        rules = {event_id for rule in output.matched_rules for event_id in rule.evidence_event_ids}
        error = output.detection_status == "DETECTION_ERROR"
        if (output.trace_id != trace_id or output.requested_mode != "AUTO" or output.is_anomaly is not decision
                or (status != 200 and not error) or output.model_score is not None
                or output.detection_source not in {"none", "rule_based"}
                or (not error and (output.detection_source != "rule_based" or output.executed_mode != "RULE_BASED"))
                or evidence != rules or (decision is True) != bool(evidence)
                or any(not rule.evidence_event_ids for rule in output.matched_rules)
                or "0" * 32 in evidence):
            raise ValueError("Invalid monitoring detection contract")
