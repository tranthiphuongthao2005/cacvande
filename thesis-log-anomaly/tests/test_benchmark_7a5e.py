import json
import sys

import pytest

from tools import collect_benchmark_7a5e as pilot


def test_deadlines_with_fake_clock():
    start = 10
    bounds = pilot.Deadlines(start)
    assert (bounds.preflight, bounds.activation, bounds.overall) == (130, 310, 802)
    assert bounds.request_deadline(305) == 310
    with pytest.raises(TimeoutError):
        bounds.request_deadline(310)
    assert bounds.response_received(309) == 429
    assert bounds.cleanup_deadline(429) == 459
    now = [459]

    def wait(seconds):
        now[0] += seconds

    assert bounds.settle(clock=lambda: now[0], wait=wait) == 759
    assert now[0] == 729
    with pytest.raises(TimeoutError):
        bounds.settle(clock=lambda: 759, wait=wait)


def test_dry_run_and_missing_approval_do_not_enter_adapter(monkeypatch, capsys):
    monkeypatch.setattr(pilot, "execute", lambda *args: pytest.fail("adapter entered"))
    args = ["pilot", "--campaign", pilot.CAMPAIGN]
    monkeypatch.setattr(sys, "argv", args)
    pilot.main()
    assert json.loads(capsys.readouterr().out)["actual_business_posts"] == 0
    monkeypatch.setattr(sys, "argv", [*args, "--live"])
    with pytest.raises(SystemExit) as caught:
        pilot.main()
    assert caught.value.code == 2


def test_approval_template_fails_and_scope_fields_are_required():
    template = pilot.read(pilot.PLAN / "operator_approval_template.json")
    output = pilot.PLAN / "fixture-not-created"
    assert not pilot.approval_matches(template, output)
    # A unit-test record only, never serialized or passed to the live entrypoint.
    scoped = {**template, "status": "APPROVED", "operator": "fixture-reviewer",
              "output_directory": output.relative_to(pilot.ROOT).as_posix()}
    assert pilot.approval_matches(scoped, output)
    for key in ("campaign_id", "configuration_id", "maximum_business_posts", "output_directory",
                "fault_scope", "rollback_plan"):
        assert not pilot.approval_matches({**scoped, key: None}, output)
    assert not pilot.approval_matches({**scoped, "maximum_business_posts": True}, output)


def test_reviewer_export_matches_verified_source_manifest():
    source = pilot.read(pilot.PLAN / "reviewer_packet_manifest.json")["items"]
    export = pilot.read(pilot.PLAN / "reviewer_packets_7a5e.json")
    assert len(export["eligible_packets"]) == 5 and len(export["missing_evidence"]) == 2
    assert sorted(export["eligible_packets"] + export["missing_evidence"], key=lambda x: x["run_id"]) == sorted(
        source, key=lambda x: x["run_id"])
    assert all(item["status"] == "NEEDS_REVIEW" for item in source)
