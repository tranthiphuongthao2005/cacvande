import json

import pytest

from tools.collection_readiness_7a6a import check


def test_default_and_selected_batch_fail_closed():
    for batch in (None, "processing-a", "retry-b"):
        result = check(batch_id=batch)
        assert result["collection_status"] == "BLOCKED"
        assert not result["all_checks_met"] and not result["execution_authorized_by_tool"]
        assert result["business_posts"] == result["provider_calls"] == 0
        assert result["independently_verified"] == 0
    assert result["fixture_verified"] == 10
    assert result["slots"]["CURRENT_LIVE"] == 2
    assert result["slots"]["HISTORICAL_LIVE"] == 3


def test_simulated_authority_never_opens_collection(tmp_path):
    path = tmp_path / "governance.json"
    path.write_text(json.dumps({"approvals": {"taxonomy": {
        "actual_approval_status": "APPROVED", "authority": "NON_BINDING", "operator_id": "fixture"
    }}}))
    assert not check(path, "normal-a")["gates"]["taxonomy"]
    with pytest.raises(ValueError, match="Unknown proposed batch"):
        check(batch_id="database-b")
