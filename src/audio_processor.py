"""
STTMeet Audio Processor
Handles audio pre-processing (converting to 16kHz mono MP3),
smart chunking with silence detection, and 5-second boundary overlap.
"""
import os
import subprocess
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional
from pydub import AudioSegment
from pydub.silence import detect_silence

from .config import (
    CHUNKS_DIR,
    DEFAULT_CHUNK_MINUTES,
    DEFAULT_MAX_SCAN_MINUTES,
    DEFAULT_SILENCE_THRESHOLD_DB,
    DEFAULT_MIN_SILENCE_MS,
    DEFAULT_OVERLAP_SECONDS,
    ensure_ffmpeg_on_path
)
from .logger import get_logger
from .utils import _ffmpeg_path, _ffprobe_path

log = get_logger(__name__)

def compute_file_hash(file_path: str) -> str:
    """Generate a quick unique signature based on file size and initial 10MB chunk."""
    hasher = hashlib.sha256()
    size = os.path.getsize(file_path)
    hasher.update(str(size).encode())
    with open(file_path, "rb") as f:
        chunk = f.read(10 * 1024 * 1024)
        hasher.update(chunk)
    return hasher.hexdigest()[:16]

def preprocess_audio(
    input_path: str,
    output_dir: Optional[Path] = None,
    progress_callback: Optional[Callable[[str], None]] = None
) -> str:
    """
    Downsample audio to 16kHz Mono MP3 at 64kbps to reduce upload size by 80-90%
    without degrading voice intelligibility for Gemini STT.
    """
    if output_dir is None:
        output_dir = CHUNKS_DIR

    file_hash = compute_file_hash(input_path)
    optimized_path = str(output_dir / f"preprocessed_{file_hash}.mp3")

    if os.path.exists(optimized_path):
        log.info("Using cached preprocessed audio: %s", optimized_path)
        if progress_callback:
            progress_callback("Found existing optimized preprocessed audio.")
        return optimized_path

    log.info("Preprocessing audio file: %s -> %s", input_path, optimized_path)
    if progress_callback:
        progress_callback("Pre-processing audio (converting to 16kHz mono MP3)...")

    cmd = [
        _ffmpeg_path(), "-y",
        "-i", input_path,
        "-ac", "1",
        "-ar", "16000",
        "-b:a", "64k",
        optimized_path
    ]

    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "check": True
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        result = subprocess.run(cmd, **kwargs)
        log.debug("ffmpeg output: %s", result.stderr.decode(errors="replace"))
    except subprocess.CalledProcessError as e:
        stderr_output = e.stderr.decode(errors="replace") if e.stderr else "(no stderr)"
        log.error("ffmpeg preprocessing failed for '%s': %s", input_path, stderr_output)
        raise RuntimeError(
            f"Audio preprocessing failed. ffmpeg error:\n{stderr_output}"
        ) from e

    log.info("Preprocessing complete: %s", optimized_path)
    return optimized_path

import json

def split_audio_into_chunks(
    audio_path: str,
    chunk_minutes: int = DEFAULT_CHUNK_MINUTES,
    max_scan_minutes: int = DEFAULT_MAX_SCAN_MINUTES,
    silence_threshold_db: int = DEFAULT_SILENCE_THRESHOLD_DB,
    min_silence_ms: int = DEFAULT_MIN_SILENCE_MS,
    overlap_seconds: int = DEFAULT_OVERLAP_SECONDS,
    progress_callback: Optional[Callable[[str, float], None]] = None
) -> List[Dict[str, Any]]:
    """
    Smart Hybrid Chunking Algorithm with automatic disk caching:
    Checks if chunks manifest already exists. If all chunk files exist,
    returns them immediately without re-slicing.
    """
    file_hash = compute_file_hash(audio_path)
    manifest_path = CHUNKS_DIR / f"manifest_{file_hash}_{chunk_minutes}m.json"

    # Check if cached chunks exist and are valid
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                cached_meta = json.load(f)
            # Verify all chunk files exist on disk
            if cached_meta and all(os.path.exists(c["file_path"]) for c in cached_meta):
                log.info("Found %d valid cached chunks for %s (%dm). Slicing skipped.", len(cached_meta), file_hash, chunk_minutes)
                if progress_callback:
                    progress_callback(f"Loaded {len(cached_meta)} audio chunks from cache.", 1.0)
                return cached_meta
        except Exception as e:
            log.warning("Could not read chunk manifest: %s. Re-chunking...", e)

    log.info(
        "Starting smart chunking: chunk=%dmin, scan=%dmin, silence_db=%d, min_silence=%dms, overlap=%ds",
        chunk_minutes, max_scan_minutes, silence_threshold_db, min_silence_ms, overlap_seconds
    )
    if progress_callback:
        progress_callback("Loading audio file for chunking...", 0.0)

    # pydub resolves ffmpeg/ffprobe through PATH; make sure the bundled copy is visible
    ensure_ffmpeg_on_path()
    audio = AudioSegment.from_file(audio_path)
    total_len_ms = len(audio)
    log.info("Audio loaded: %.1f seconds total.", total_len_ms / 1000)

    # If chunk_minutes is 0 or negative, treat the entire file as a single un-sliced chunk (No Chunking)
    if chunk_minutes <= 0:
        single_chunk = {
            "chunk_index": 0,
            "file_path": audio_path,
            "start_ms": 0,
            "end_ms": total_len_ms,
            "duration_ms": total_len_ms,
            "offset_seconds": 0.0
        }
        manifest_data = [single_chunk]
        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, indent=2)
        except Exception as err:
            log.warning("Could not cache single chunk manifest: %s", err)
        if progress_callback:
            progress_callback("Ready (No chunking mode: 1 single file).", 1.0)
        return manifest_data

    target_ms = chunk_minutes * 60 * 1000
    scan_ms = max_scan_minutes * 60 * 1000
    overlap_ms = overlap_seconds * 1000

    chunks_meta = []
    current_pos_ms = 0
    chunk_index = 0
    file_hash = compute_file_hash(audio_path)

    while current_pos_ms < total_len_ms:
        nominal_end_ms = current_pos_ms + target_ms
        
        if nominal_end_ms >= total_len_ms:
            # Final remaining portion
            cut_point_ms = total_len_ms
            chunk_slice = audio[current_pos_ms:]
        else:
            # Scan window between nominal_end_ms and nominal_end_ms + scan_ms
            scan_end_ms = min(total_len_ms, nominal_end_ms + scan_ms)
            scan_segment = audio[nominal_end_ms:scan_end_ms]
            
            silence_ranges = detect_silence(
                scan_segment,
                min_silence_len=min_silence_ms,
                silence_thresh=silence_threshold_db
            )
            
            if silence_ranges:
                # Cut at the midpoint of the earliest detected silence
                first_silence_start, first_silence_end = silence_ranges[0]
                silence_mid = (first_silence_start + first_silence_end) // 2
                cut_point_ms = nominal_end_ms + silence_mid
            else:
                # No silence detected within scan window; perform fallback cut
                cut_point_ms = scan_end_ms
            
            # Slice audio up to cut_point + overlap
            slice_end_ms = min(total_len_ms, cut_point_ms + overlap_ms)
            chunk_slice = audio[current_pos_ms:slice_end_ms]

        chunk_filename = f"chunk_{file_hash}_{chunk_index:03d}.mp3"
        chunk_filepath = str(CHUNKS_DIR / chunk_filename)
        
        # Export chunk slice to disk
        chunk_slice.export(chunk_filepath, format="mp3", bitrate="64k")

        chunk_meta = {
            "chunk_index": chunk_index,
            "file_path": chunk_filepath,
            "start_ms": current_pos_ms,
            "end_ms": cut_point_ms,
            "duration_ms": len(chunk_slice),
            "offset_seconds": current_pos_ms / 1000.0
        }
        chunks_meta.append(chunk_meta)

        chunk_index += 1
        current_pos_ms = cut_point_ms

        if progress_callback:
            progress_pct = min(1.0, current_pos_ms / total_len_ms)
            progress_callback(
                f"Generated chunk {chunk_index} ({current_pos_ms // 1000}s / {total_len_ms // 1000}s)",
                progress_pct
            )

    # Save manifest for fast caching on subsequent runs
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(chunks_meta, f, indent=2)
        log.info("Saved chunk manifest: %s", manifest_path)
    except Exception as e:
        log.warning("Failed to save chunk manifest: %s", e)

    return chunks_meta
