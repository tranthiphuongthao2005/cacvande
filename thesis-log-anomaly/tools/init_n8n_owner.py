"""Initialize the first n8n owner on loopback once, without printing credentials."""

import secrets
from pathlib import Path
from time import monotonic, sleep

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / ".env.n8n-owner"
    with httpx.Client(base_url="http://127.0.0.1:5678", timeout=12, trust_env=False) as http:
        deadline = monotonic() + 240
        while monotonic() < deadline:
            try:
                if http.get("/healthz/readiness").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            sleep(2)
        else:
            raise SystemExit("n8n did not become ready")
        pending = http.get("/rest/settings").raise_for_status().json()["data"]["userManagement"]["showSetupOnFirstLoad"]
        if path.exists():
            saved = dict(line.split("=", 1) for line in path.read_text(encoding="ascii").splitlines())
        elif pending:
            saved = {"N8N_OWNER_EMAIL": "owner@thesis-lab.example",
                     "N8N_OWNER_PASSWORD": "Aa7" + secrets.token_hex(24)}
            with path.open("x", encoding="ascii") as stream:
                for name, value in saved.items():
                    stream.write(f"{name}={value}\n")
        else:
            print("n8n owner is already configured")
            return
        email, password = saved["N8N_OWNER_EMAIL"], saved["N8N_OWNER_PASSWORD"]
        if pending:
            try:
                response = http.post("/rest/owner/setup", json={
                    "email": email, "firstName": "Thesis", "lastName": "Operator", "password": password,
                }, timeout=60)
            except httpx.TimeoutException:
                print("Owner setup response timed out; checking saved credential.")
            else:
                if response.status_code not in (200, 201):
                    raise SystemExit(f"Local n8n owner setup failed (HTTP {response.status_code})")
        response = http.post("/rest/login", json={"emailOrLdapLoginId": email, "password": password})
        if response.status_code != 200:
            raise SystemExit(f"Local n8n owner login failed (HTTP {response.status_code})")
    print("Local n8n owner authentication verified with .env.n8n-owner")


if __name__ == "__main__":
    main()
