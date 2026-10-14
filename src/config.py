"""
STTMeet Configuration Module
Handles environment variables, API keys, cache folders, and tunable audio settings.
"""
import os
from pathlib import Path
from dotenv import load_dotenv, set_key

# Base Directory of Project
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

# Load existing environment variables
load_dotenv(dotenv_path=ENV_PATH)

# Cache & Checkpoint Directory
CACHE_DIR = BASE_DIR / ".sttmeet_cache"
CHUNKS_DIR = CACHE_DIR / "chunks"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

# Default Processing Parameters
DEFAULT_CHUNK_MINUTES = 25          # Target duration for audio chunks
DEFAULT_MAX_SCAN_MINUTES = 2        # Search forward window for natural silence
DEFAULT_SILENCE_THRESHOLD_DB = -40  # Silence threshold in dBFS
DEFAULT_MIN_SILENCE_MS = 500        # Minimum silence duration to identify a cut (ms)
DEFAULT_OVERLAP_SECONDS = 5         # Audio overlap between chunks for continuity

# Model Configuration (Cloud)
# Default transcription model: gemini-3-flash
MODEL_NAME = "gemini-3-flash"
FALLBACK_MODELS = [
    "gemini-3-flash",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite"
]

# Dedicated model for Minutes, Summaries, and Action Items to conserve limits
MINUTES_MODEL_NAME = "gemini-3.5-flash-lite"
MINUTES_FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3-flash",
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
