import ast
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from tools import collection_gate_7a6b as gate
from tools.cohort_review_7a6b import compare, import_review
from tools.benchmark_readiness_7a5i import HANDOFF
from tools import smoke_producer_accounting
from tools.import_review_7a3 import signature


@pytest.fixture
def permit(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "PLAN", tmp_path)
    monkeypatch.setattr(gate, "check", lambda *a, **kw: {"all_checks_met": True})
    record = {"approval_id": "a" * 32, "expires_at": "2027-01-02T00:00:00Z", "campaign_id": "normal-a",
              "configuration_id": "normal-a", "decision_source": "OPERATOR", "output_directory": "run",
              "maximum_business_posts": 1, "retries": 0, "overall_seconds": 450}
    return tmp_path / "approval.json", tmp_path / "run", record


def make_gate(file, output, record):
    file.write_text(json.dumps({"collection_batches": {"normal-a": record}}), encoding="utf-8")
    return gate.PostGate(file, "normal-a", output, clock=lambda: datetime(2027, 1, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize("changes", [
    {"decision_source": "ADVISOR_SIMULATION"}, {"campaign_id": "other"},
    {"configuration_id": "processing-a"}, {"expires_at": "2026-12-31T00:00:00Z"},
    {"output_directory": "other"}, {"maximum_business_posts": 2},
])
def test_wrong_scope_blocks_before_post(permit, changes):
    file, output, record = permit
    client = Mock()
    with pytest.raises(gate.CollectionBlocked):
        gate.business_post(make_gate(file, output, {**record, **changes}), client, "/orders", before_send=Mock())
    client.post.assert_not_called()


def test_recheck_and_replay_at_transport_boundary(permit, monkeypatch):
    file, output, record = permit
    admitted = make_gate(file, output, record)
    output.mkdir()
    client = Mock()
    with monkeypatch.context() as change:
        change.setattr(gate, "check", lambda *a, **kw: {"all_checks_met": False})
        with pytest.raises(gate.CollectionBlocked):
            gate.business_post(admitted, client, "/orders", before_send=Mock())
    client.post.assert_not_called()

    client.post.side_effect = TimeoutError
    with pytest.raises(TimeoutError):
        gate.business_post(admitted, client, "/orders", before_send=Mock())
    with pytest.raises(gate.CollectionBlocked):
        gate.business_post(admitted, client, "/orders", before_send=Mock())
    client.post.assert_called_once_with("/orders")


def test_missing_gate_and_missing_reviewer_identity(tmp_path):
    client = Mock()
    with pytest.raises(gate.CollectionBlocked):
        gate.business_post(None, client, "/orders", before_send=Mock())
    client.post.assert_not_called()
    signed = tmp_path / "unsigned.json"
    decision = json.loads((HANDOFF / "reviewer_decision_template.json").read_text())
    signed.write_text(json.dumps({"decision": decision, "signature": ""}))
    allowlist = tmp_path / "registry.json"
    allowlist.write_text("{}")
    out = tmp_path / "receipt.json"
    with pytest.raises(ValueError, match="Unauthorized reviewer"):
        import_review(HANDOFF, signed, allowlist, out)
    assert not out.exists()


def test_different_name_does_not_prove_independence():
    row = {"id": "a", "mechanism": "timeout", "position": "Product", "edge": "Order/Product",
           "retry": "1", "handling": "propagated", "group_hint": "x"}
    result = compare(row, {**row, "id": "b"})
    assert result["classification"] == "REPEATED_OR_EQUIVALENT"
    assert result["independence"] == "UNVERIFIED"


def test_production_collector_routes_only_through_gated_post(tmp_path):
    tree = ast.parse(Path(smoke_producer_accounting.__file__).read_text(encoding="utf-8"))
    calls = [node.func for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert sum(isinstance(call, ast.Name) and call.id == "business_post" for call in calls) == 1
    assert not any(isinstance(call, ast.Attribute) and call.attr in {"post", "request", "send"} for call in calls)
    output = tmp_path / "never-created"
    with pytest.raises(gate.CollectionBlocked):
        smoke_producer_accounting.run(output)
    assert not output.exists()


def test_consumed_approval_survives_collector_restart(permit):
    file, output, record = permit
    admitted = make_gate(file, output, record)
    output.mkdir()
    gate.business_post(admitted, Mock(), "/orders", before_send=Mock())
    # Change the output so the child cannot reject merely because the previous output exists.
    file.write_text(json.dumps({"collection_batches": {"normal-a": {**record, "output_directory": "new"}}}))
    child = """
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from tools import collection_gate_7a6b as gate
gate.ROOT = gate.PLAN = Path(sys.argv[1])
gate.check = lambda *args, **kwargs: {"all_checks_met": True}
client = Mock()
try:
    admitted = gate.PostGate(gate.ROOT / 'approval.json', 'normal-a', gate.ROOT / 'new',
                             clock=lambda: datetime(2027, 1, 1, tzinfo=timezone.utc))
    gate.business_post(admitted, client, '/orders', before_send=Mock())
except gate.CollectionBlocked:
    client.post.assert_not_called()
    assert not (gate.ROOT / 'new').exists()
else:
    raise AssertionError('Replay permitted')
"""
    subprocess.run([sys.executable, "-B", "-c", child, str(output.parent)], check=True, timeout=20)


def test_import_receipt_fixture_and_evidence_rejection(tmp_path):
    decision = json.loads((HANDOFF / "reviewer_decision_template.json").read_text())
    decision.update(reviewer_id="fixture-only", reviewed_at="2027-01-01T00:00:00Z",
                    decision="INCONCLUSIVE", justification="Fixture only")
    key = "ab" * 32
    registry, signed, actors, out = (tmp_path / name for name in ("registry", "signed", "actors", "receipt"))
    registry.write_text(json.dumps({decision["reviewer_id"]: {"key_hex": key, "run_ids": [decision["run_id"]]}}))
    actors.write_text(json.dumps({"run_id": decision["run_id"], "creator_and_approver_ids": ["fixture-operator"]}))
    bad = {**decision, "decision": "VERIFIED"}
    signed.write_text(json.dumps({"decision": bad, "signature": signature(bad, key)}))
    with pytest.raises(ValueError, match="at least one"):
        import_review(HANDOFF, signed, registry, out, campaign_actors=actors)
    assert not out.exists()
    signed.write_text(json.dumps({"decision": decision, "signature": signature(decision, key)}))
    assert import_review(HANDOFF, signed, registry, out, campaign_actors=actors)["status"] == "IMPORTED_RECEIPT"
    assert json.loads(out.read_text())["status"] == "INCONCLUSIVE"
    with pytest.raises(FileExistsError):
        import_review(HANDOFF, signed, registry, out, campaign_actors=actors)
