"""Create local credentials once; never echo secret values."""

import secrets
from pathlib import Path

NAMES = ("ELASTIC_PASSWORD", "KIBANA_SYSTEM_PASSWORD", "FILEBEAT_WRITER_PASSWORD",
         "KIBANA_SECURITY_KEY", "KIBANA_OBJECTS_KEY", "KIBANA_REPORTING_KEY")

if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / ".env.elk"
    with target.open("x", encoding="ascii") as stream:
        for name in NAMES:
            stream.write(f"{name}={secrets.token_hex(24)}\n")
    print("Created .env.elk without displaying credentials.")
