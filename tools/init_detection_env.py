"""Provision a local read-only Elasticsearch API key, without printing it."""

import json
from pathlib import Path
from urllib.request import Request, urlopen
import base64

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / ".env.detection"
    if output.exists():
        raise FileExistsError(output)
    env = dict(line.split("=", 1) for line in (ROOT / ".env.elk").read_text().splitlines())
    auth = base64.b64encode(f"elastic:{env['ELASTIC_PASSWORD']}".encode()).decode()
    body = {"name": "thesis-detection-local", "expiration": "30d",
            "role_descriptors": {"trace_reader": {
                "indices": [{"names": ["thesis-logs-*"], "privileges": ["read"]}],
            }}}
    req = Request("http://127.0.0.1:9200/_security/api_key", data=json.dumps(body).encode(),
                  headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    with urlopen(req, timeout=30) as response:
        credentials = json.load(response)
    with output.open("x", encoding="ascii") as stream:
        stream.write(f"DETECTION_ES_API_KEY={credentials['encoded']}\n")
    print("Created .env.detection with a 30-day read-only key.")


if __name__ == "__main__":
    main()
