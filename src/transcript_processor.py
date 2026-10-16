"""
STTMeet Transcript Post-Processor
Handles:
1. Regex-based timestamp offset adjustments so chunk 2 continues from chunk 1's duration.
2. Boundary overlap deduplication.
3. Speaker label mapping (e.g. "Speaker 1" -> "En. Razak").
"""
import re
from typing import Dict, List

def parse_time_to_seconds(time_str: str) -> int:
    """Convert 'MM:SS' or 'HH:MM:SS' into total integer seconds."""
    parts = [int(p) for p in time_str.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0

def format_seconds_to_timestamp(total_seconds: int) -> str:
    """Format total seconds into [HH:MM:SS] if >= 1 hour, otherwise [MM:SS]."""
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"
    return f"[{minutes:02d}:{secs:02d}]"

def adjust_chunk_timestamps(transcript_text: str, offset_seconds: float) -> str:
    """
    Find all bracketed timestamps like [01:23] or [01:23:45] and add offset_seconds to each.
    """
    offset_sec_int = int(round(offset_seconds))
    if offset_sec_int <= 0:
        return transcript_text

    def replace_ts(match):
        raw_ts = match.group(1)
        base_seconds = parse_time_to_seconds(raw_ts)
        new_seconds = base_seconds + offset_sec_int
        return format_seconds_to_timestamp(new_seconds)

    # Matches [MM:SS] or [HH:MM:SS]
    pattern = r'\[(\d{1,2}:\d{2}(?::\d{2})?)\]'
    return re.sub(pattern, replace_ts, transcript_text)

def deduplicate_overlap(
    prev_transcript: str,
    curr_transcript: str,
    overlap_window_lines: int = 5
) -> str:
    """
    Examines the boundary between previous chunk and current chunk.
    If the start of the current chunk repeats dialogue from the tail of the previous chunk,
    removes the duplicate lines.
    """
    if not prev_transcript or not curr_transcript:
        return curr_transcript

    prev_lines = [l.strip() for l in prev_transcript.splitlines() if l.strip()]
    curr_lines = [l.strip() for l in curr_transcript.splitlines() if l.strip()]

    if not prev_lines or not curr_lines:
        return curr_transcript

    # Normalize dialogue line by stripping timestamp for fuzzy matching
    def strip_meta(line: str) -> str:
        cleaned = re.sub(r'^\[.*?\]\s*', '', line)
        cleaned = re.sub(r'^Speaker\s*\d+:\s*', '', cleaned, flags=re.IGNORECASE)
        return cleaned.strip().lower()

    prev_tail_normalized = [strip_meta(l) for l in prev_lines[-overlap_window_lines:] if strip_meta(l)]

    cut_index = 0
    for idx, line in enumerate(curr_lines[:overlap_window_lines]):
        norm_line = strip_meta(line)
        if not norm_line:
            continue
        # Check if line appears verbatim in tail
        if norm_line in prev_tail_normalized:
            cut_index = idx + 1

    if cut_index > 0:
        return "\n".join(curr_lines[cut_index:])

    return curr_transcript

def extract_speakers(transcript_text: str) -> List[str]:
    """Find all unique 'Speaker X' mentions in the transcript."""
    speakers = set(re.findall(r'Speaker\s*(\d+)', transcript_text, re.IGNORECASE))
    sorted_speakers = sorted([f"Speaker {s}" for s in speakers], key=lambda x: int(x.split()[1]))
    return sorted_speakers

def apply_speaker_mapping(transcript_text: str, speaker_map: Dict[str, str]) -> str:
    """
    Replace placeholder speaker tags with actual names.
    e.g. {"Speaker 1": "En. Ahmad", "Speaker 2": "Pn. Siti"}
    """
    result = transcript_text
    for placeholder, real_name in speaker_map.items():
        if real_name and real_name.strip():
            # Match word boundary
            pattern = re.compile(re.escape(placeholder) + r'\b', re.IGNORECASE)
            result = pattern.sub(real_name.strip(), result)
    return result
