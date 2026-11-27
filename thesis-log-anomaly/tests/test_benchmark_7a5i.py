import json

from tools.benchmark_readiness_7a5i import HANDOFF, plan, reviewer_packet


def test_planner_defaults_to_blocked_and_forecasts_zero():
    report = plan()
    assert not report["all_checks_met"] and not report["execution_authorized_by_tool"]
    assert report["forecast_model_calls"] == report["actual_api_calls"] == 0
    assert report["design_call_cap"] == 34
    assert not report["gates"]["snapshot_integrity"]


def test_simulation_cannot_act_as_real_approval(tmp_path):
    governance = tmp_path / "governance.json"
    governance.write_text(json.dumps({"approvals": {"taxonomy": {
        "authority": "NON_BINDING", "actual_approval_status": "APPROVED", "operator_id": "fixture"
    }}}))
    report = plan(governance)
    assert not report["gates"]["taxonomy"] and not report["gates"]["protocol"]


def test_existing_reviewer_packet_can_be_audited_without_identity():
    assert reviewer_packet(HANDOFF) == {"references_checked": 13, "event_count": 4, "status": "NEEDS_REVIEW"}
