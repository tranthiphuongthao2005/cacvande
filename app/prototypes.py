"""Pure prototype math and disjoint-pool checks for a future approved support bundle."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Lineage:
    trace_id: str
    event_ids: frozenset[str]
    group_id: str


def validate_pools(support, development, evaluation):
    if not all((support, development, evaluation)):
        raise ValueError("All pools must be nonempty")
    traces, events, groups = set(), set(), set()
    for pool in (support, development, evaluation):
        pool_groups = set()
        for row in pool:
            if not row.trace_id or not row.event_ids or not row.group_id:
                raise ValueError("Missing trace, event or independence group")
            if row.trace_id in traces or events & row.event_ids or row.group_id in groups:
                raise ValueError("Trace, event or scenario-family leakage")
            traces.add(row.trace_id)
            events.update(row.event_ids)
            pool_groups.add(row.group_id)
        groups.update(pool_groups)


class PrototypeScorer:
    def __init__(self, support, labels, lengths, method):
        import torch

        size = len(support)
        if method not in {"single", "length_aware_multi"} or not size == len(labels) == len(lengths):
            raise ValueError("Invalid support configuration")
        if any(label not in (0, 1) for label in labels) or any(length < 1 for length in lengths):
            raise ValueError("Invalid support labels or lengths")
        support = self._unit(support)
        normal = [i for i, label in enumerate(labels) if label == 0]
        anomaly = [i for i, label in enumerate(labels) if label == 1]
        if not normal or not anomaly:
            raise ValueError("Both support classes are required")
        short = [i for i in anomaly if lengths[i] <= 4]
        long = [i for i in anomaly if lengths[i] > 4]
        self.fallback = method == "length_aware_multi" and min(len(short), len(long)) < 2
        groups = [short, long] if method == "length_aware_multi" and not self.fallback else [anomaly]
        self.normal = self._unit(support[normal].mean(dim=0, keepdim=True))
        self.anomaly = torch.cat([self._unit(support[group].mean(dim=0, keepdim=True)) for group in groups])

    @staticmethod
    def _unit(rows):
        import torch
        import torch.nn.functional as F

        if rows.ndim != 2 or not torch.isfinite(rows).all() or (rows.norm(dim=1) <= 1e-12).any():
            raise ValueError("Invalid prototype embedding or norm")
        return F.normalize(rows, dim=1)

    def scores(self, queries):
        query = self._unit(queries)
        return (query @ self.anomaly.T).amax(dim=1) - (query @ self.normal.T).flatten()


def reject_support_query_overlap(query, support):
    ids = {event.event_id for event in query.events}
    if any(query.trace_id == row.trace_id or ids & row.event_ids for row in support):
        raise ValueError("Support/query overlap")


class PreparedScoring:
    """Wire an approved feature adapter and frozen reference for future deployment."""

    def __init__(self, *, encoder, features, protocol_id, model_version, method,
                 support, development, evaluation, embeddings, labels, lengths):
        validate_pools(support, development, evaluation)
        if len(support) != len(embeddings) or not protocol_id or not model_version:
            raise ValueError("Missing support/model lineage")
        self.encoder = encoder
        self.features = features
        self.support = tuple(support)
        self.protocol_id = protocol_id
        self.model_version = model_version
        self.method = method
        self.scorer = PrototypeScorer(embeddings, labels, lengths, method)

    def detect(self, session):
        if session.source_metadata.completeness != "complete":
            raise ValueError("Incomplete trace")
        reject_support_query_overlap(session, self.support)
        arrays, warnings = self.features(session)
        value = self.scorer.scores(self.encoder.encode(arrays)).item()
        return {"model_version": self.model_version, "support_protocol_id": self.protocol_id,
                "scoring_method": self.method, "anomaly_score": value, "threshold": 0.0,
                "predicted_label": int(value > 0.0), "preprocessing_warnings": warnings,
                "fallback": self.scorer.fallback}
