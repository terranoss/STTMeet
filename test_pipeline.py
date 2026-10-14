# Unit tests for STTMeet logic modules
import json
import tempfile
from pathlib import Path

from src.transcript_processor import (
    parse_time_to_seconds,
    format_seconds_to_timestamp,
    adjust_chunk_timestamps,
    deduplicate_overlap,
    extract_speakers,
    apply_speaker_mapping
)
from src.utils import format_duration, estimate_cost_and_tokens
from src.session_store import (
    DEFAULT_SETTINGS,
    SCHEMA_VERSION,
    build_session_payload,
    load_session,
    normalize_settings,
    save_session,
    session_path
)

def test_time_conversions():
    assert parse_time_to_seconds("01:30") == 90
    assert parse_time_to_seconds("01:00:00") == 3600
    assert format_seconds_to_timestamp(90) == "[01:30]"
    assert format_seconds_to_timestamp(3665) == "[01:01:05]"

def test_adjust_chunk_timestamps():
    sample = "[00:15] Speaker 1: Helo selamat pagi.\n[01:30] Speaker 2: Selamat pagi."
    # Shift by 25 minutes = 1500 seconds
    adjusted = adjust_chunk_timestamps(sample, offset_seconds=1500)
    assert "[25:15]" in adjusted
    assert "[26:30]" in adjusted

def test_speaker_mapping():
    transcript = "[00:01] Speaker 1: Setuju.\n[00:05] Speaker 2: Baiklah."
    mapping = {"Speaker 1": "En. Razak", "Speaker 2": "Pn. Faridah"}
    mapped = apply_speaker_mapping(transcript, mapping)
    assert "En. Razak:" in mapped
    assert "Pn. Faridah:" in mapped
    assert "Speaker 1" not in mapped

def test_deduplicate_overlap():
    prev = "[10:00] Speaker 1: Kita teruskan.\n[10:15] Speaker 2: Baik Tuan."
    curr = "[10:15] Speaker 2: Baik Tuan.\n[10:20] Speaker 1: Agenda seterusnya."
    deduped = deduplicate_overlap(prev, curr)
    assert "[10:20] Speaker 1: Agenda seterusnya." in deduped
    assert deduped.count("Baik Tuan") == 0

def test_cost_estimator():
    res = estimate_cost_and_tokens(3600) # 1 hour
    assert res["estimated_input_tokens"] == 3600 * 32
    assert res["estimated_cost_usd"] > 0
    assert "1h 00m 00s" in res["formatted_duration"]

def _sample_settings():
    return {
        "engine": "☁️ Gemini 3.5 Flash",
        "language": "Bilingual",
        "chunk_minutes": 20,
        "preprocess": False
    }

def _sample_status():
    return {
        "steps": {"step1": "done", "step2": "done", "step3": "error", "step4": "pending"},
        "chunks": [
            {"index": 0, "status": "done", "error": ""},
            {"index": 1, "status": "error", "error": "quota exceeded"}
        ],
        "progress": 0.6
    }

def test_session_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = session_path(Path(tmp), "abc123")
        assert path.name == "session_abc123.json"

        payload = build_session_payload(
            audio_hash="abc123",
            audio_path="D:/meetings/agm.mp3",
            settings=_sample_settings(),
            status=_sample_status(),
            raw_transcript="[00:01] Speaker 1: Setuju.",
            processed_transcript="[00:01] En. Razak: Setuju.",
            generated_minutes="# Summary\n...",
            detected_speakers=["Speaker 1"],
            speaker_mapping={"Speaker 1": "En. Razak"}
        )
        assert payload["schema_version"] == SCHEMA_VERSION
        assert save_session(payload, path)

        loaded = load_session(path)
        assert loaded is not None
        assert loaded["audio_hash"] == "abc123"
        assert loaded["settings"] == _sample_settings()
        assert loaded["status"]["steps"]["step3"] == "error"
        assert loaded["status"]["chunks"][1]["error"] == "quota exceeded"
        assert loaded["speaker_mapping"] == {"Speaker 1": "En. Razak"}
        assert loaded["processed_transcript"] == "[00:01] En. Razak: Setuju."

def test_session_never_stores_api_key():
    payload = build_session_payload(
        audio_hash="abc123",
        audio_path="D:/meetings/agm.mp3",
        settings=_sample_settings(),
        status=_sample_status()
    )
    serialized = json.dumps(payload)
    assert "GEMINI_API_KEY" not in serialized
    assert "api_key" not in serialized

def test_session_loads_v1_without_settings():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "session_legacy.json"
        path.write_text(json.dumps({
            "audio_hash": "legacy",
            "raw_transcript": "old transcript",
            "generated_minutes": "old minutes",
            "detected_speakers": ["Speaker 2"],
            "updated_at": "2026-01-01T00:00:00"
        }), encoding="utf-8")

        loaded = load_session(path)
        assert loaded is not None
        assert loaded["schema_version"] == 1
        assert loaded["settings"] == DEFAULT_SETTINGS
        assert loaded["status"]["steps"]["step1"] == "pending"
        assert loaded["status"]["chunks"] == []
        assert loaded["processed_transcript"] == "old transcript"
        assert loaded["speaker_mapping"] == {}

def test_normalize_settings_rejects_stale_values():
    stale = {
        "engine": "💻 Malaysian-Whisper (Local)",
        "language": "Klingon",
        "chunk_minutes": 5,
        "preprocess": "yes"
    }
    assert normalize_settings(stale) == DEFAULT_SETTINGS
    assert normalize_settings(None) == DEFAULT_SETTINGS

    # Unusable chunk sizes fall back to the default rather than raising
    assert normalize_settings({"chunk_minutes": "banana"})["chunk_minutes"] == DEFAULT_SETTINGS["chunk_minutes"]

def test_load_session_missing_and_corrupt():
    with tempfile.TemporaryDirectory() as tmp:
        assert load_session(Path(tmp) / "session_nope.json") is None

        corrupt = Path(tmp) / "session_bad.json"
        corrupt.write_text("{not valid json", encoding="utf-8")
        assert load_session(corrupt) is None

if __name__ == "__main__":
    test_time_conversions()
    test_adjust_chunk_timestamps()
    test_speaker_mapping()
    test_deduplicate_overlap()
    test_cost_estimator()
    test_session_roundtrip()
    test_session_never_stores_api_key()
    test_session_loads_v1_without_settings()
    test_normalize_settings_rejects_stale_values()
    test_load_session_missing_and_corrupt()
    print("All unit tests passed successfully!")
