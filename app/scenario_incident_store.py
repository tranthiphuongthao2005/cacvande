"""Legacy scenario ledger shared with the incident read API."""

import json
import sqlite3
from contextlib import closing
from time import time
from uuid import uuid4

RETENTION = 7 * 24 * 3600


class Ledger:
    def __init__(self, path):
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS incidents (
                request_digest TEXT PRIMARY KEY, signature TEXT NOT NULL, incident_id TEXT UNIQUE NOT NULL,
                created REAL NOT NULL, result TEXT, notification TEXT)""")

    def claim(self, key, signature):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM incidents WHERE created < ?", (time() - RETENTION,))
            row = db.execute("SELECT signature, incident_id, result FROM incidents WHERE request_digest=?",
                             (key,)).fetchone()
            if row:
                stored, identity, result = row
                return ("conflict", None) if stored != signature else ("replay", json.loads(result)) if result else (
                    "pending", identity)
            identity = uuid4().hex
            db.execute("INSERT INTO incidents VALUES (?, ?, ?, ?, NULL, NULL)", (key, signature, identity, time()))
            return "new", identity

    def finish(self, key, result):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            notification = None
            if result["analysis_status"] == "COMPLETED":
                recent = db.execute(
                    "SELECT 1 FROM incidents WHERE signature=? AND created>=? AND notification IS NOT NULL",
                    (result["scope_signature"], time() - 3600),
                ).fetchone()
                if not recent:
                    notification = {"type": "local_analysis_review", "incident_id": result["incident_id"],
                                    "observations": result["report"]["observations"],
                                    "suspected_cause": result["report"]["suspected_root_cause"],
                                    "evidence_event_ids": result["report"]["evidence_event_ids"],
                                    "limitations": result["report"]["limitations"],
                                    "recommended_checks": result["report"]["recommended_checks"]}
            result["notification_status"] = "LOCAL_STORED" if notification else "SUPPRESSED"
            result.pop("scope_signature")
            db.execute("UPDATE incidents SET result=?, notification=? WHERE request_digest=?",
                       (json.dumps(result), json.dumps(notification) if notification else None, key))

    def read(self, identity):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT result FROM incidents WHERE incident_id=? AND created>=?",
                             (identity, time() - RETENTION)).fetchone()
        return json.loads(row[0]) if row and row[0] else None
