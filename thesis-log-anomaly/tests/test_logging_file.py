import json
import os
import subprocess
import sys


def test_file_and_docker_handlers_emit_same_event(tmp_path):
    path = tmp_path / "app.jsonl"
    program = """
from fastapi.testclient import TestClient
from app.api import Settings, create_app

class Repo:
    async def initialize(self):
        pass

app = create_app(Settings('user','unused'), repository=Repo())
with TestClient(app) as client:
    assert client.get('/health').status_code == 200
"""
    result = subprocess.run([sys.executable, "-B", "-c", program], capture_output=True, text=True,
                            env={**os.environ, "APP_LOG_PATH": str(path)}, check=True)
    file_event = json.loads(path.read_text())
    console_event = json.loads(result.stderr.splitlines()[-1])
    assert file_event == console_event
    assert len(file_event["event_id"]) == 32 and len(file_event["request_id"]) == 16
    assert file_event["trace_id"] and file_event["span_id"]
    assert file_event["status"] == 200 and isinstance(file_event["duration_ms"], (int, float))
