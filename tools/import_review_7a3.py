"""Import a human-authored decision using out-of-band reviewer authorization."""

import argparse
import hashlib
import hmac
import re
from pathlib import Path

from app.contracts import StrictRecord
from app.micro_dataset import canonical, checksum
from tools.collect_benchmark_7a1 import write
from tools.verify_ground_truth_7a2 import read, validate_review


class Decision(StrictRecord):
    run_id: str
    reviewer_id: str
    reviewed_at: str
    decision: str
    reviewed_evidence_references: list[str]
    justification: str


def signature(decision, key):
    secret = bytes.fromhex(key.strip())
    if len(secret) < 32:
        raise ValueError("Reviewer key must be at least 32 bytes")
    return hmac.new(secret, canonical(decision).encode("utf-8"), hashlib.sha256).hexdigest()


def verify(signed, dossier, allowlist):
    if set(signed) != {"decision", "signature"} or not isinstance(signed["signature"], str):
        raise ValueError("Missing or malformed reviewer signature")
    decision = Decision.model_validate(signed["decision"])
    reviewer = decision.reviewer_id
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", reviewer) or reviewer not in allowlist:
        raise ValueError("Unauthorized reviewer")
    permissions = allowlist[reviewer]
    if decision.run_id not in permissions["run_ids"]:
        raise ValueError("Reviewer not authorized for this run")
    if not hmac.compare_digest(signature(signed["decision"], permissions["key_hex"]), signed["signature"]):
        raise ValueError("Invalid reviewer signature")
    tag = "dossier:" + checksum(dossier)
    available = {tag} | {"event:" + i for i in dossier["supporting_evidence"]["event_ids"]}
    refs = decision.reviewed_evidence_references
    if len(refs) != len(set(refs)) or tag not in refs or not set(refs) <= available:
        raise ValueError("Reviewer evidence references do not match dossier")
    if decision.decision == "VERIFIED" and not any(item.startswith("event:") for item in refs):
        raise ValueError("Verification requires at least one reviewed event")
    validate_review({"run_id": decision.run_id, "dossier_sha256": checksum(dossier),
                     "status": decision.decision, "reviewer_id": reviewer,
                     "reviewed_at": decision.reviewed_at, "reason": decision.justification}, dossier)
    return {"status": decision.decision, "reviewer_id": reviewer, "run_id": decision.run_id,
            "review": signed, "dossier_sha256": checksum(dossier), "auth_scheme": "reviewer-hmac-v1"}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--decision", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--sign-key-file", type=Path)
    cli.add_argument("--allowlist", type=Path)
    cli.add_argument("--dossier", type=Path)
    args = cli.parse_args()
    if args.sign_key_file and not (args.allowlist or args.dossier):
        decision = Decision.model_validate(read(args.decision)).model_dump()
        write(args.output, {"decision": decision, "signature": signature(
            decision, args.sign_key_file.read_text(encoding="ascii"))})
        print("Signed supplied review decision.")
    elif args.allowlist and args.dossier and not args.sign_key_file:
        result = verify(read(args.decision), read(args.dossier), read(args.allowlist))
        write(args.output, result)
        print("Authenticated review imported; pilot labels unchanged.")
    else:
        cli.error("Use --sign-key-file, or --allowlist with --dossier")


if __name__ == "__main__":
    main()
