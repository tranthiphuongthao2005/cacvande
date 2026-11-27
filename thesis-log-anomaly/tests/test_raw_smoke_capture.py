import hashlib
from types import SimpleNamespace

from app import llm_provider
from tools import raw_smoke_capture


def test_container_capture_is_scoped_bounded_and_exclusive(monkeypatch, tmp_path):
    path = tmp_path / "model-response.txt"
    monkeypatch.setattr(llm_provider, "RAW_RESPONSE_PATH", path)
    monkeypatch.setenv("LLM_GEMINI_RAW_CAPTURE_ENABLED", "1")
    monkeypatch.setenv("LLM_GEMINI_SMOKE_APPROVAL_ID", "gemini-smoke-7b1-007")
    monkeypatch.setenv("LLM_GEMINI_RAW_CAPTURE_APPROVAL_ID", "gemini-smoke-7b1-007")
    monkeypatch.setenv("LLM_GEMINI_SMOKE_TRACE_ID", "a" * 32)

    assert llm_provider.capture_raw_gemini_response("private", "b" * 32) == "SCOPE_MISMATCH"
    assert llm_provider.capture_raw_gemini_response("x" * 65537, "a" * 32) == "TOO_LARGE"
    assert llm_provider.capture_raw_gemini_response("private", "a" * 32) == "SAVED"
    assert llm_provider.capture_raw_gemini_response("other", "a" * 32) == "ALREADY_CAPTURED"
    assert path.read_text() == "private"


def test_operator_copies_exact_bytes_to_local_file_once(monkeypatch, tmp_path):
    raw = b'{"value":"HTTP 502"}'
    monkeypatch.setattr(raw_smoke_capture.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=0, stdout=raw, stderr=b""))
    record = raw_smoke_capture.copy_one_raw_response(
        "gemini-smoke-7b1-007", "single_service", tmp_path)
    assert record == {
        "status": "SAVED",
        "path": "experiments/gemini_smoke_7b1/private/gemini-smoke-7b1-007.single_service.raw.txt",
        "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
    }
    assert (tmp_path / record["path"]).read_bytes() == raw
    assert raw_smoke_capture.copy_one_raw_response(
        "gemini-smoke-7b1-007", "single_service", tmp_path) == {"status": "ALREADY_PRESENT"}
