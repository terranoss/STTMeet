"""
STTMeet Checkpoint Store

The Checkpoint is the on-disk record of which Chunks are done and what they transcribed,
written after every Chunk so an interrupted Pipeline run resumes instead of re-paying for
work already done.

Deliberately separate from session_store. A Checkpoint is the pipeline's own record of
half-finished transcription; a session is the desktop app's record of a whole workspace
(settings, status, speaker mapping, generated documents). The pipeline writes the former
and knows nothing of the latter -- see ADR 0001.

Flat and UI-independent, like session_store and cancellation.
"""
import json
from pathlib import Path
from typing import Any, Dict

from .logger import get_logger

log = get_logger(__name__)

CHECKPOINT_PREFIX = "checkpoint_"


def checkpoint_path(directory, audio_hash: str) -> Path:
    """Where the Checkpoint for one Audio file lives."""
    return Path(directory) / f"{CHECKPOINT_PREFIX}{audio_hash}.json"


def load_checkpoint(directory, audio_hash: str, chunk_minutes: int) -> Dict[str, str]:
    """
    The Chunks a previous run of this Audio file already transcribed, keyed by index.

    An absent, unreadable or malformed Checkpoint is not an error: it is a run that has
    not started yet, and the caller transcribes everything as though nothing were banked.
    A Checkpoint taken at a different Chunking size is also refused, because those Chunks
    are not this run's Chunks and stitching them together would be a lie.
    """
    path = checkpoint_path(directory, audio_hash)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload: Any = json.load(handle)
    except FileNotFoundError:
        return {}
    except Exception as err:
        log.warning("Could not read Checkpoint %s; starting fresh: %s", path, err)
        return {}

    if not isinstance(payload, dict) or payload.get("audio_hash") != audio_hash:
        log.warning("Checkpoint %s does not belong to this Audio file; starting fresh.", path)
        return {}

    if _recorded_chunk_minutes(payload) != chunk_minutes:
        log.warning(
            "Checkpoint %s was written at %s-minute Chunking; this run uses %s. Starting fresh.",
            path, _recorded_chunk_minutes(payload), chunk_minutes,
        )
        return {}

    return _done_chunks(payload.get("chunks"))


def save_checkpoint(
    directory, audio_hash: str, chunk_minutes: int, chunks: Dict[str, str]
) -> bool:
    """
    Write the Checkpoint, recording which Chunks are done and what they transcribed.

    Written after every completed Chunk, so an interruption costs at most the Chunk in
    flight. The Chunking size is recorded alongside so a later run can tell whether these
    are the same Chunks it would produce itself.
    """
    payload = {
        "audio_hash": audio_hash,
        "chunk_minutes": chunk_minutes,
        "chunks": dict(chunks),
    }
    path = checkpoint_path(directory, audio_hash)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        return True
    except Exception as err:
        # A Checkpoint that cannot be written costs the next run its resume, not this run
        # its Transcript. Say so and carry on transcribing.
        log.warning("Could not write Checkpoint %s: %s", path, err)
        return False


def _recorded_chunk_minutes(payload: Dict[str, Any]) -> int:
    """The Chunking size a Checkpoint was written at; an absent one means 'off'."""
    try:
        return int(payload.get("chunk_minutes") or 0)
    except (TypeError, ValueError):
        return 0


def _done_chunks(raw: Any) -> Dict[str, str]:
    """The transcribed Chunks in a Checkpoint's payload, keeping only real text."""
    if not isinstance(raw, dict):
        return {}
    done = {}
    for index, text in raw.items():
        try:
            key = str(int(index))
        except (TypeError, ValueError):
            continue
        if isinstance(text, str) and text.strip():
            done[key] = text
    return done