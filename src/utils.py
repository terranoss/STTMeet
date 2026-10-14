"""
STTMeet Utility Functions
Handles FFmpeg validation, audio duration analysis, and token/cost estimations.
"""
import shutil
import subprocess
from pathlib import Path
from typing import Tuple, Dict, Any

def check_ffmpeg() -> Tuple[bool, str]:
    """
    Check if FFmpeg is installed and accessible in the system PATH.
    Returns (is_installed, version_or_message).
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return False, "FFmpeg was not found in system PATH."
    
    try:
        res = subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        first_line = res.stdout.splitlines()[0] if res.stdout else "Installed"
        return True, first_line
    except Exception as e:
        return False, f"Error verifying FFmpeg: {str(e)}"

def format_duration(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    total_seconds = int(round(seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes:02d}m {secs:02d}s"

def get_audio_duration(file_path: str) -> float:
    """
    Get audio duration in seconds using ffprobe.
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        # Fallback to pydub if ffprobe has specific argument parsing difference
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(file_path)
            return len(audio) / 1000.0
        except Exception as e:
            raise RuntimeError(f"Could not determine audio duration: {e}")

def estimate_cost_and_tokens(duration_seconds: float) -> Dict[str, Any]:
    """
    Estimate Gemini 1.5 Pro input/output tokens and cost.
    Audio tokens are counted at approximately 32 tokens per second.
    """
    input_audio_tokens = int(duration_seconds * 32)
    # Estimated transcript text tokens (~130-160 words/min => ~200 tokens/min => ~3.3 tokens/sec)
    estimated_output_tokens = int(duration_seconds * 3.5)
    
    # Gemini 3.5 Flash Pricing (Standard Paid Tier, Free Tier is $0.00):
    # Audio input: ~$0.35 per 1M tokens
    # Output: ~$1.05 per 1M tokens
    tier_input_rate = 0.35
    tier_output_rate = 1.05

    input_cost = (input_audio_tokens / 1_000_000.0) * tier_input_rate
    output_cost = (estimated_output_tokens / 1_000_000.0) * tier_output_rate
    total_cost = input_cost + output_cost

    return {
        "duration_seconds": duration_seconds,
        "formatted_duration": format_duration(duration_seconds),
        "estimated_input_tokens": input_audio_tokens,
        "estimated_output_tokens": estimated_output_tokens,
        "estimated_cost_usd": round(total_cost, 3)
    }
