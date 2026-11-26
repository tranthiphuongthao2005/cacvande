"""Provision a separate, read-only Elasticsearch credential for Context API."""

import base64
import json
from urllib.request import Request, urlopen

from tools.init_detection_env import ROOT


def main():
    destination = ROOT / ".env.context"
    if destination.exists():
        raise FileExistsError(destination)
    config = dict(row.split("=", 1) for row in (ROOT / ".env.elk").read_text().splitlines())
    token = base64.b64encode(f"elastic:{config['ELASTIC_PASSWORD']}".encode()).decode()
    descriptor = {"name": "thesis-context-local", "expiration": "30d",
                  "role_descriptors": {"context_reader": {"indices": [
                      {"names": ["thesis-logs-*"], "privileges": ["read"]}]}}}
    request = Request("http://127.0.0.1:9200/_security/api_key", data=json.dumps(descriptor).encode(),
                      headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"})
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
    with destination.open("x", encoding="ascii") as stream:
        stream.write(f"CONTEXT_ES_API_KEY={result['encoded']}\n")
    print("Created .env.context with a 30-day read-only key.")


if __name__ == "__main__":
    main()
