"""Producer-side evidence for one explicitly armed lab trace."""

import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

VERSION = "producer-accounting-v1"


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Accounting:
    def __init__(self, path, run_id, trace_id, service):
        self.path, self.run_id, self.trace_id, self.service = path, run_id, trace_id, service
        self.scope = (run_id, trace_id)
        if not all(re.fullmatch(r"[0-9a-f]{32}", item) and int(item, 16) for item in self.scope):
            raise ValueError("Invalid accounting scope")
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    run TEXT, trace TEXT, sequence INTEGER, event_id TEXT, emission_timestamp TEXT,
                    late INTEGER, payload_hash TEXT, stderr TEXT, file TEXT,
                    PRIMARY KEY(run,trace,sequence), UNIQUE(run,trace,event_id)
                );
                CREATE TABLE IF NOT EXISTS seals (run TEXT, trace TEXT, body TEXT, PRIMARY KEY(run,trace));
            """)

    def create(self, event_id, emitted_at):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            sequence, = db.execute("SELECT coalesce(max(sequence),0)+1 FROM events WHERE run=? AND trace=?",
                                   self.scope).fetchone()
            late = db.execute("SELECT 1 FROM seals WHERE run=? AND trace=?", self.scope).fetchone() is not None
            db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,NULL,NULL,NULL)",
                       (*self.scope, sequence, event_id, emitted_at, int(late)))

    def outcome(self, event_id, sink, state, payload):
        if sink not in {"file", "stderr"} or state not in {"WRITE_FAILED", "FLUSH_FAILED", "LOG_FLUSHED"}:
            raise ValueError("Invalid accounting outcome")
        payload_hash = hashlib.sha256(payload.encode()).hexdigest() if payload is not None else None
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                f"UPDATE events SET {sink}=?, payload_hash=coalesce(payload_hash,?) WHERE run=? AND trace=? AND event_id=?",
                (state, payload_hash, *self.scope, event_id),
            )

    def summary(self, *, seal=False):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("""SELECT sequence,event_id,emission_timestamp,late,payload_hash,stderr,file
                                  FROM events WHERE run=? AND trace=? ORDER BY sequence""", self.scope).fetchall()
            existing = db.execute("SELECT body FROM seals WHERE run=? AND trace=?", self.scope).fetchone()
            events = [{"event_sequence": i, "event_id": eid, "emission_timestamp": t, "after_seal": bool(late),
                       "payload_sha256": payload_hash, "producer_status": "EVENT_CREATED",
                       "stderr_status": stderr, "file_status": file,
                       "logging_handoff_status": "UNCONFIRMED"}
                      for i, eid, t, late, payload_hash, stderr, file in rows]
            count = sum(e["stderr_status"] == e["file_status"] == "LOG_FLUSHED" for e in events)
            body = {"run_id": self.run_id, "trace_id": self.trace_id, "service_name": self.service,
                    "accounting_version": VERSION, "expected_event_count": len(events),
                    "expected_event_ids": [e["event_id"] for e in events], "emitted_event_count": count,
                    "failed_emission_count": len(events) - count, "flush_status": "FLUSHED" if events and count == len(events)
                    else "UNVERIFIED", "events": events}
            if seal and not existing:
                if not events or any(e["file_status"] is None or e["stderr_status"] is None for e in events):
                    raise ValueError("Producer has pending writes or no accounted events")
                document = {"seal_version": "producer-scope-seal-v1", "closed_at": stamp(), "summary": body}
                existing = (json.dumps({**document, "sha256": digest(document)}),)
                db.execute("INSERT INTO seals VALUES (?,?,?)", (*self.scope, existing[0]))
            return {"summary": body, "seal": json.loads(existing[0]) if existing else None,
                    "late_event_ids": [e["event_id"] for e in events if e["after_seal"]]}


def enabled():
    run_id, trace_id = (os.getenv(k) for k in ("ACCOUNTING_RUN_ID", "ACCOUNTING_TRACE_ID"))
    if run_id is None and trace_id is None:
        return None
    path = Path(os.environ["APP_LOG_PATH"])
    return Accounting(path.with_suffix(".accounting.sqlite"), run_id or "", trace_id or "", path.stem)


if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser()
    cli.add_argument("action", choices=("seal", "inspect"))
    args = cli.parse_args()
    tracker = enabled()
    if tracker is None:
        cli.error("Accounting is not armed")
    print(json.dumps(tracker.summary(seal=args.action == "seal")))
