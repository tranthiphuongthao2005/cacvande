from tools.validate_7a5d import CASCADE, PLAN, read, validate


def test_7a5d_artifact_audit():
    result = validate()
    assert (result["sufficient_for_review"], result["missing_evidence"]) == (5, 2)
    assert result["smoke_hashes"] == 15
    assert result["research_hashes"] == 63


def test_7a5d_supplement_has_no_verdict():
    packet, = [p for p in read(PLAN / "reviewer_packet_manifest.json")["items"] if p["run_id"] == CASCADE]
    assert packet["status"] == "NEEDS_REVIEW"
    supplement = packet["candidate_supplement"]
    assert supplement["authorship"] == "SYSTEM_PREPARED_NOT_REVIEWED"
    assert supplement["handling"] == ["propagated"]
    assert len(set(supplement["event_ids"])) == 3
