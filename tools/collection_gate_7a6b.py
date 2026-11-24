"""Runtime admission for the bounded Normal and Processing collectors."""
import json
import os
import re
from datetime import datetime, timezone

from tools.collect_benchmark_7a1 import digest
from tools.collection_readiness_7a6a import check
from tools.validate_7a5d import PLAN, ROOT, read


class CollectionBlocked(RuntimeError):
    pass


SCOPES = {
    "normal-a": ("normal-a", 450),
    "processing-a-development-pilot": ("processing-a", 792),
    "timeout-a-development-acceptance": ("timeout-a", 792),
    "database-a-development-acceptance": ("database-a", 792),
    "cascade-a-development-acceptance": ("cascade-a", 792),
}


class PostGate:
    def __init__(self, governance, campaign, output, *, clock=None):
        self.governance = governance
        self.campaign = campaign
        self.output = output.resolve()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.governance_hash = digest(governance) if governance else None
        self.ledger = PLAN / "collection_approval_usage"
        self.check(reserved=False)

    def scope(self):
        return SCOPES[self.campaign]

    def output_parent(self):
        return PLAN

    def check_binding(self, entry):
        """Additional scope checks for specialized admissions."""

    def check(self, *, reserved):
        try:
            if not self.governance or digest(self.governance) != self.governance_hash:
                raise ValueError("Missing or changed governance")
            config, minimum_budget = self.scope()
            entry = read(self.governance)["collection_batches"][config]
            self.check_binding(entry)
            approval_id = entry["approval_id"]
            expires = datetime.fromisoformat(entry["expires_at"].replace("Z", "+00:00"))
            if (not re.fullmatch(r"[a-f0-9]{32}", approval_id)
                    or expires.tzinfo is None or self.clock() >= expires
                    or entry["campaign_id"] != self.campaign or entry["configuration_id"] != config
                    or entry.get("decision_source") != "OPERATOR"
                    or entry["output_directory"] != self.output.relative_to(ROOT).as_posix()
                    or type(entry["maximum_business_posts"]) is not int or entry["maximum_business_posts"] != 1
                    or type(entry["retries"]) is not int or entry["retries"] != 0
                    or entry["overall_seconds"] < minimum_budget
                    or self.output.parent != self.output_parent().resolve()
                    or (not reserved and (PLAN / "collection_runtime_lock").exists())
                    or (reserved and not self.output.is_dir())
                    or (self.ledger / approval_id).exists()
                    or not check(self.governance, config, reserved_output=self.output if reserved else None,
                                 output_parent=self.output_parent())["all_checks_met"]):
                raise ValueError("Runtime scope or readiness check failed")
            if digest(self.governance) != self.governance_hash:
                raise ValueError("Governance changed during checks")
            return approval_id
        except (OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
            raise CollectionBlocked("Collection approval missing, invalid, expired or already used") from exc

    def consume(self):
        approval_id = self.check(reserved=True)
        self.ledger.mkdir(exist_ok=True)
        try:
            with (self.ledger / approval_id).open("x", encoding="utf-8") as stream:
                json.dump({"campaign_id": self.campaign, "output_directory": self.output.relative_to(ROOT).as_posix(),
                           "governance_sha256": self.governance_hash, "consumed_at": self.clock().isoformat()}, stream)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError as exc:
            raise CollectionBlocked("Collection approval already used") from exc


def business_post(gate, client, url, *, before_send, **kwargs):
    if gate is None:
        raise CollectionBlocked("No runtime gate")
    gate.consume()
    before_send()
    return client.post(url, **kwargs)


class RuntimeLease:
    """Persist a stop marker if rollback/postflight cannot be verified."""
    def __init__(self, output):
        self.path = PLAN / "collection_runtime_lock"
        self.output = output

    def acquire(self):
        try:
            with self.path.open("x", encoding="utf-8") as stream:
                stream.write(self.output.name + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError as exc:
            raise CollectionBlocked("Runtime is occupied or an earlier rollback needs operator recovery") from exc

    def release(self):
        self.path.unlink()
