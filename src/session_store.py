"""
STTMeet Session Store
Pure, UI-independent serialization for meeting sessions.

A session captures everything needed to bring the workspace back exactly as the
user left it: the settings used for the run, the status of each pipeline step and
audio chunk, and the transcription/minutes output.

The API key is deliberately never stored here - it lives in .env only.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 2

# Which generation of the Minutes a session's cached documents came from. Bump this
# whenever the Template prompts change what a document looks like, and every cached
# document written before the bump reads as a miss and is generated again -- which is
# the only way an older document, made by prompts that never asked for time anchors,
# stops being served to someone who has just been given the feature.
#
# The version describes the cache as a whole rather than each entry: a change to the
# prompts changes every Template at once, and a cache allowed to serve some Templates
# from one generation and others from another is exactly the half-migrated state the
# bump exists to prevent.
MINUTES_CACHE_VERSION = 1

# A session written before the cache recorded a version at all reads as older than
# any number, since 0 is below every version this build has used.
NO_MINUTES_CACHE_VERSION = 0

# Must mirror the option lists in src/ui/app_window.py
DEFAULT_SETTINGS = {
    "engine": "⚡ Gemini Cloud (Auto-Failover)",
    "language": "Bahasa Melayu",
    "chunk_minutes": 25,
    "preprocess": True,
    "template": "action_minutes",
}

VALID_ENGINES = [
    "⚡ Gemini Cloud (Auto-Failover)",
    "☁️ Gemini 3.8 Flash",
    "☁️ Gemini 3.5 Flash",
    "☁️ Gemini 3.5 Flash Lite",
]
VALID_LANGUAGES = ["Bahasa Melayu", "English"]
VALID_TEMPLATES = [
    "action_minutes",
    "discussion_minutes",
    "three_column",
    "board_governance",
]
VALID_CHUNK_MINUTES = [0, 15, 20, 25, 30, 45]

VALID_STEP_STATES = ["pending", "working", "done", "error"]
VALID_CHUNK_STATES = ["pending", "working", "done", "error"]

STEP_KEYS = ["step1", "step2", "step3", "step4"]


def session_path(cache_dir: Path, audio_hash: str) -> Path:
    """Absolute path of the session file for a given audio file hash."""
    return Path(cache_dir) / f"session_{audio_hash}.json"


def build_session_payload(
    audio_hash: str,
    audio_path: Optional[str],
    settings: Dict[str, Any],
    status: Dict[str, Any],
    raw_transcript: str = "",
    processed_transcript: str = "",
    generated_minutes: str = "",
    generated_recap: str = "",
    generated_actions: str = "",
    detected_speakers: Optional[List[str]] = None,
    speaker_mapping: Optional[Dict[str, str]] = None,
    cached_minutes_by_template: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Assemble a versioned session payload. Chunk text is NOT stored here."""
    return {
        "schema_version": SCHEMA_VERSION,
        "audio_hash": audio_hash,
        "audio_path": audio_path or "",
        "settings": normalize_settings(settings),
        "status": normalize_status(status),
        "speaker_mapping": dict(speaker_mapping or {}),
        "raw_transcript": raw_transcript or "",
        "processed_transcript": processed_transcript or "",
        "generated_minutes": generated_minutes or "",
        "generated_recap": generated_recap or "",
        "generated_actions": generated_actions or "",
        "detected_speakers": list(detected_speakers or []),
        "cached_minutes_by_template": dict(cached_minutes_by_template or {}),
        # The version belongs to the cache as a whole, so it sits beside the entries
        # rather than inside each one: the entries stay the plain text every consumer
        # already reads, and invalidating them is one field rather than a walk.
        "minutes_cache_version": MINUTES_CACHE_VERSION,
        "updated_at": datetime.now().isoformat(),
    }


def normalize_settings(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Coerce stored settings into currently valid values.
    Anything unrecognized (stale model names, older builds) falls back to defaults.
    """
    raw = raw or {}
    result = dict(DEFAULT_SETTINGS)

    engine = raw.get("engine")
    if engine in VALID_ENGINES:
        result["engine"] = engine

    language = raw.get("language")
    if language in VALID_LANGUAGES:
        result["language"] = language

    try:
        chunk_mins = int(raw.get("chunk_minutes"))
    except (TypeError, ValueError):
        chunk_mins = DEFAULT_SETTINGS["chunk_minutes"]
    if chunk_mins in VALID_CHUNK_MINUTES:
        result["chunk_minutes"] = chunk_mins

    preprocess = raw.get("preprocess")
    if isinstance(preprocess, bool):
        result["preprocess"] = preprocess

    template = raw.get("template")
    if template in VALID_TEMPLATES:
        result["template"] = template

    return result


def normalize_status(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Coerce stored step/chunk status into valid states, defaulting to pending."""
    raw = raw or {}

    steps = {}
    stored_steps = raw.get("steps") or {}
    for key in STEP_KEYS:
        state = stored_steps.get(key)
        steps[key] = state if state in VALID_STEP_STATES else "pending"

    chunks = []
    for entry in raw.get("chunks") or []:
        try:
            index = int(entry.get("index"))
        except (TypeError, ValueError):
            continue
        state = entry.get("status")
        chunks.append({
            "index": index,
            "status": state if state in VALID_CHUNK_STATES else "pending",
            "error": str(entry.get("error") or ""),
        })

    try:
        progress = float(raw.get("progress") or 0.0)
    except (TypeError, ValueError):
        progress = 0.0
    progress = min(max(progress, 0.0), 1.0)

    return {"steps": steps, "chunks": chunks, "progress": progress}


def minutes_cache_is_current(session: Optional[Dict[str, Any]]) -> bool:
    """
    Whether a loaded session's cached Minutes were generated by this build.

    False means the next generation produces them again. False covers the session that
    recorded no version at all, which is what every session written before the cache
    was versioned looks like, as well as a version from a build that has since moved on.
    """
    if not session:
        return False
    try:
        stored = int(session.get("minutes_cache_version", NO_MINUTES_CACHE_VERSION))
    except (TypeError, ValueError):
        return False
    return stored == MINUTES_CACHE_VERSION


def save_session(payload: Dict[str, Any], path: Path) -> bool:
    """Write a session payload to disk. Returns True on success."""
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def load_session(path: Path) -> Optional[Dict[str, Any]]:
    """
    Read and normalize a session file.
    Returns None when missing/corrupt. Version 1 files (no settings/status)
    load cleanly with default settings and pending status.
    """
    path = Path(path)
    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    return {
        "schema_version": data.get("schema_version", 1),
        "audio_hash": data.get("audio_hash", ""),
        "audio_path": data.get("audio_path", ""),
        "settings": normalize_settings(data.get("settings")),
        "status": normalize_status(data.get("status")),
        "speaker_mapping": data.get("speaker_mapping") or {},
        "raw_transcript": data.get("raw_transcript", "") or "",
        # v1 files stored no processed_transcript; the raw one is the best available
        "processed_transcript": data.get("processed_transcript") or data.get("raw_transcript", "") or "",
        "generated_minutes": data.get("generated_minutes", "") or "",
        "generated_recap": data.get("generated_recap", "") or "",
        "generated_actions": data.get("generated_actions", "") or "",
        "detected_speakers": data.get("detected_speakers") or [],
        # The cache and its version are written by build_session_payload, so a session
        # that had no reader for them was one where every cached document was paid for
        # again on every reopen. They are returned together, since a version with
        # nothing to describe is not worth carrying.
        "cached_minutes_by_template": data.get("cached_minutes_by_template") or {},
        "minutes_cache_version": data.get("minutes_cache_version", NO_MINUTES_CACHE_VERSION),
        "updated_at": data.get("updated_at", ""),
    }