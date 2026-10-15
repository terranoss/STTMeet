"""
STTMeet Preferences Store
Global, UI-independent persistence for application preferences such as the
interface language.

Distinct from session_store.py, which captures per-meeting state keyed by the
audio file hash. A UI language is a property of the machine, not of a meeting,
so it lives here in a single small JSON file.
"""
import json
from typing import Any, Dict

from .config import CACHE_DIR

PREFS_PATH = CACHE_DIR / "prefs.json"


def load_prefs() -> Dict[str, Any]:
    """
    Read preferences, returning {} when the file is missing, unreadable,
    corrupt, or not a JSON object. Never raises.
    """
    try:
        with open(PREFS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_pref(key: str, value: Any) -> bool:
    """
    Merge one preference into the store and write it back.
    Returns True on success. A failed write is non-fatal: the in-session value
    still applies and the app keeps running.
    """
    prefs = load_prefs()
    prefs[key] = value
    try:
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def get_pref(key: str, default: Any = None) -> Any:
    return load_prefs().get(key, default)