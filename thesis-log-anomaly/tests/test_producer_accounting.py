import io
import logging
from pathlib import Path

from app.producer_accounting import Accounting, stamp
from app.telemetry import AccountedStream
from app.telemetry_receipts import decode, resolve
from tools.smoke_producer_accounting import SERVICES, compare
from tools.verify_ground_truth_7a2 import read
from app.incident_context import IncidentContext


def test_producer_sequence_seal_and_after_seal(tmp_path):
    a = Accounting(tmp_path / "accounting.sqlite", "a" * 32, "b" * 32, "order")
    for eid in ("c" * 32, "d" * 32):
        a.create(eid, stamp())
        for sink in ("stderr", "file"):
            a.outcome(eid, sink, "LOG_FLUSHED", "payload")
    frozen = a.summary(seal=True)
    assert frozen["summary"]["expected_event_count"] == frozen["summary"]["emitted_event_count"] == 2
    assert [e["event_sequence"] for e in frozen["summary"]["events"]] == [1, 2]
    a.create("e" * 32, stamp())
    live = a.summary()
    assert live["seal"] == frozen["seal"]
    assert live["late_event_ids"] == ["e" * 32]
    assert live["summary"]["events"][-1]["logging_handoff_status"] == "UNCONFIRMED"


def test_flush_failure_distinguished_from_handoff(tmp_path):
    class Broken(io.StringIO):
        def flush(self):
            raise OSError("fixture")

    a = Accounting(tmp_path / "accounting.sqlite", "a" * 32, "b" * 32, "order")
    eid = "c" * 32
    a.create(eid, stamp())
    h = AccountedStream(Broken())
    h.handleError = lambda _: None
    rec = logging.LogRecord("test", 20, "", 0, "event", (), None)
    rec.accounting, rec.event_id = a, eid
    h.emit(rec)
    summary = a.summary()["summary"]
    assert summary["events"][0]["stderr_status"] == "FLUSH_FAILED"
    assert summary["failed_emission_count"] == 1 and summary["flush_status"] == "UNVERIFIED"


def test_multiservice_detects_missing_duplicate_delayed_and_late(tmp_path):
    seals, inspections, es, docker = {}, {}, [], []
    for index, service in enumerate(SERVICES):
        a = Accounting(tmp_path / f"{service}.sqlite", "a" * 32, "b" * 32, service)
        eid = f"{index + 1:032x}"
        a.create(eid, stamp())
        # Absent Docker content is a deliberately incomplete fixture.
        for sink in ("stderr", "file"):
            a.outcome(eid, sink, "LOG_FLUSHED", "fixture")
        seals[service] = a.summary(seal=True)
        es.append(eid)
        if index == 2:
            a.create("d" * 32, stamp())
        inspections[service] = a.summary()
    missing = compare(seals, inspections, docker, es[:-1])["warnings"]
    assert {"ES_EVENT_SET_MISMATCH", "DOCKER_EVENT_SET_MISMATCH", "EVENT_AFTER_SEAL"} <= set(missing)
    delayed = compare(seals, inspections, docker, es)["warnings"]
    assert "ES_EVENT_SET_MISMATCH" not in delayed and "EVENT_AFTER_SEAL" in delayed
    assert compare(seals, inspections, docker, es + es[:1])["elasticsearch"]["duplicate"] == es[:1]


def test_7a3_bundle_backward_compatible():
    root = Path(__file__).resolve().parents[1] / "experiments/benchmark_7a3_smoke"
    context = IncidentContext.model_validate(read(root / "snapshot.json"))
    seal, receipt = decode(read(next((root / "receipts").glob("*.json"))))
    assert seal.producer_accounting_version is None
    observed, provenance = resolve(context, root / "receipts")
    assert observed["ingestion_reconciled"] and not observed["trace_complete"]
    assert "accounting_version" not in provenance
