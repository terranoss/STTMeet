"""
STTMeet Configuration Module
Handles environment variables, API keys, cache folders, and tunable audio settings.
"""
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv, set_key


def is_frozen() -> bool:
    """True when running from a compiled/frozen build (Nuitka, PyInstaller)."""
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def get_base_dir() -> Path:
    """
    Writable base directory for .env, cache and logs.

    Development: the repository root (so the checked-in .env and
    .sttmeet_cache/ keep working).
    Frozen/installed: %LOCALAPPDATA%\\STTMeet, because the install directory
    (C:\\Program Files) is not writable by standard users.
    """
    if is_frozen():
        local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(local_app_data) / "STTMeet"
    return Path(__file__).resolve().parent.parent


def get_bundled_ffmpeg_dir() -> Path:
    """
    Directory holding the FFmpeg binaries shipped inside the installer.

    Frozen builds place them next to the executable as ``ffmpeg\\``. In
    development there is no bundled copy and this returns a non-existent path.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent / "ffmpeg"
    return Path(__file__).resolve().parent.parent / "vendor" / "ffmpeg" / "bin"


def ensure_ffmpeg_on_path() -> Optional[Path]:
    """
    Prepend the bundled FFmpeg directory to PATH (once per process).

    Makes ``ffmpeg`` / ``ffprobe`` resolvable by every subprocess call without
    touching each call site. Returns the directory that was added, or None.
    """
    global _FFMPEG_PATH_ADDED
    if _FFMPEG_PATH_ADDED:
        return _FFMPEG_PATH_ADDED

    ffmpeg_dir = get_bundled_ffmpeg_dir()
    if (ffmpeg_dir / "ffmpeg.exe").exists() or (ffmpeg_dir / "ffmpeg").exists():
        current = os.environ.get("PATH", "")
        entry = str(ffmpeg_dir)
        if entry.lower() not in current.lower().split(os.pathsep):
            os.environ["PATH"] = entry + os.pathsep + current
        _FFMPEG_PATH_ADDED = ffmpeg_dir
    return _FFMPEG_PATH_ADDED


_FFMPEG_PATH_ADDED: Optional[Path] = None


def suppress_subprocess_window():
    """Ensure child processes (ffmpeg, ffprobe, etc.) run silently without flashing console windows on Windows."""
    if sys.platform == "win32":
        import subprocess
        if not getattr(subprocess, "_sttmeet_silent_patched", False):
            orig_init = subprocess.Popen.__init__

            def _silent_popen(self, *args, **kwargs):
                no_window = subprocess.CREATE_NO_WINDOW
                kwargs["creationflags"] = kwargs.get("creationflags", 0) | no_window
                return orig_init(self, *args, **kwargs)

            subprocess.Popen.__init__ = _silent_popen
            subprocess._sttmeet_silent_patched = True


suppress_subprocess_window()


# Base Directory of Project
BASE_DIR = get_base_dir()
BASE_DIR.mkdir(parents=True, exist_ok=True)
ENV_PATH = BASE_DIR / ".env"

# Load existing environment variables
load_dotenv(dotenv_path=ENV_PATH)

# Cache & Checkpoint Directory
CACHE_DIR = BASE_DIR / ".sttmeet_cache"
CHUNKS_DIR = CACHE_DIR / "chunks"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

# Documentation Folder (bundled into the frozen build via --add-data=docs;docs)
def get_docs_dir() -> Path:
    """Locate the docs/ folder in a source checkout or a PyInstaller build."""
    candidates = []
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "docs")
    candidates.append(get_base_dir() / "docs")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


DOCS_DIR = get_docs_dir()

# Google AI Studio page where users create a free Gemini API key
API_KEY_URL = "https://aistudio.google.com/apikey"

# Default Processing Parameters
DEFAULT_CHUNK_MINUTES = 25          # Target duration for audio chunks
DEFAULT_MAX_SCAN_MINUTES = 2        # Search forward window for natural silence
DEFAULT_SILENCE_THRESHOLD_DB = -40  # Silence threshold in dBFS
DEFAULT_MIN_SILENCE_MS = 500        # Minimum silence duration to identify a cut (ms)
DEFAULT_OVERLAP_SECONDS = 5         # Audio overlap between chunks for continuity

# Model Configuration (Cloud)
# Default transcription model: gemini-3.8-flash (active GA, 1M context, high accuracy)
MODEL_NAME = "gemini-3.8-flash"
FALLBACK_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite"
]

# Dedicated model for Minutes, Summaries, and Action Items to conserve limits
MINUTES_MODEL_NAME = "gemini-3.5-flash-lite"
MINUTES_FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.5-flash"
]

MAX_OUTPUT_TOKENS = 65536
TEMPERATURE = 0.1

def get_api_key() -> str:
    """Retrieve Gemini API Key from environment or .env file."""
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    return os.environ.get("GEMINI_API_KEY", "").strip()

def save_api_key(api_key: str) -> None:
    """Save or update Gemini API Key in the local .env file."""
    api_key = api_key.strip()
    if not ENV_PATH.exists():
        ENV_PATH.touch()
    set_key(str(ENV_PATH), "GEMINI_API_KEY", api_key)
    os.environ["GEMINI_API_KEY"] = api_key
