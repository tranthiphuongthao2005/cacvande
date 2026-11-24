import json
import sys

import pytest

from tools import collect_benchmark_7a5c as smoke


@pytest.mark.parametrize("arguments,code", [
    (["--live"], 2),
    (["--live", "--operator-confirmed"], 2),
    (["--max-requests", "2"], 2),
])
def test_cli_rejects_missing_live_gates(monkeypatch, arguments, code):
    monkeypatch.setattr(sys, "argv", ["collector", "--campaign", "normal-a", *arguments])
    monkeypatch.setattr(smoke, "live", lambda _: pytest.fail("Live adapter invoked"))
    with pytest.raises(SystemExit) as failure:
        smoke.main()
    assert failure.value.code == code


def test_default_cli_is_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["collector", "--campaign", "normal-a"])
    monkeypatch.setattr(smoke, "live", lambda _: pytest.fail("Live adapter invoked"))
    smoke.main()
    record = json.loads(capsys.readouterr().out)
    assert record["mode"] == "DRY_RUN" and record["target_requests"] == 0
    assert record["target_request_cap"] == 1 and record["maximum_seconds"] == 450


def test_existing_output_blocks_execution(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke, "OUT_ROOT", tmp_path.parent)
    monkeypatch.setattr(smoke, "live", lambda _: pytest.fail("Live adapter invoked"))
    monkeypatch.setattr(sys, "argv", ["collector", "--campaign", "normal-a", "--live",
                                     "--operator-confirmed", "--output", str(tmp_path)])
    with pytest.raises(SystemExit) as failure:
        smoke.main()
    assert failure.value.code == 2
