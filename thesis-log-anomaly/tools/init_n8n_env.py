"""Create local workflow secrets once without printing their contents."""

import secrets
from pathlib import Path


def main():
    path = Path(__file__).resolve().parents[1] / ".env.n8n"
    with path.open("x", encoding="ascii") as stream:
        stream.write(f"N8N_ENCRYPTION_KEY={secrets.token_hex(32)}\n")
        stream.write(f"WORKFLOW_TRIGGER_TOKEN={secrets.token_urlsafe(40)}\n")
    print("Created .env.n8n")


if __name__ == "__main__":
    main()
