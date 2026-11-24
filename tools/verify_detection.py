"""Read the seven observed trace IDs and audit candidate features without model inference."""

import argparse
import json
import sys
from pathlib import Path

import httpx

from app.mecolog_runtime import candidate_resources, build_candidates, load_encoder
from app.trace_store import TraceStore

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research", type=Path, default=ROOT.parent / "tuanmartin-MeCoLog-8c446ac")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, default=ROOT / "experiments/elk_verification.json")
    parser.add_argument("--features", action="store_true")
    parser.add_argument("--ml-site-packages", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    receipt = json.loads(args.receipt.read_text())
    config = dict(line.split("=", 1) for line in (ROOT / ".env.detection").read_text().splitlines())
    with httpx.Client(base_url="http://127.0.0.1:9200", trust_env=False, timeout=25,
                      headers={"Authorization": f"ApiKey {config['DETECTION_ES_API_KEY']}"}) as client:
        store = TraceStore(client)
        sessions = [store.fetch(row["trace_id"]) for row in receipt["scenarios"]]
        for row, session in zip(receipt["scenarios"], sessions):
            if session is None or len(session.events) != row["indexed_events"]:
                raise ValueError("Historical trace not available or event count changed")
    report = {"traces": [{"trace_id": session.trace_id, "candidate_root": session.service_name,
                          "event_count": len(session.events),
                          "services": sorted({event.service_name for event in session.events}),
                          "completeness": session.source_metadata.completeness} for session in sessions],
              "scoring": "NOT_READY_FOR_SCORING", "model_forward_executed": False}
    if args.features:
        if args.ml_site_packages:
            sys.path.append(str(args.ml_site_packages.resolve(strict=True)))
        import torch
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        model = load_encoder(args.research).model
        report["strict_load"] = {"tensors": len(model.state_dict()), "eval_mode": not model.training,
                                 "trainable_parameters": sum(p.requires_grad for p in model.parameters())}
        del model
        drain, vocab, embed, replay_count = candidate_resources(args.research)
        arrays, stats = build_candidates(sessions, drain, vocab, embed)
        report["drain_verified_lines"] = replay_count
        report["candidate_tensor_shapes"] = {key: list(array.shape) for key, array in arrays.items()}
        report["candidate_features"] = stats
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print(f"Verified {len(sessions)} observed traces. Report: {args.output}")


if __name__ == "__main__":
    main()
