"""
STTMeet Logger
Centralized rotating file logger for the application.
Writes to sttmeet.log next to the application data directory
(repo root in development, %LOCALAPPDATA%\\STTMeet when installed).
"""
import logging
import sys
from logging.handlers import RotatingFileHandler

from .config import BASE_DIR

LOG_FILE = BASE_DIR / "sttmeet.log"
MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
BACKUP_COUNT = 3              # Keep last 3 rotated files

_initialized = False


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger that writes to both the rotating log file
    and the console (stdout). Safe to call multiple times.
    """
    global _initialized

    logger = logging.getLogger(name)

    if not _initialized:
        logger.setLevel(logging.DEBUG)

        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # --- Rotating file handler ---
        try:
            file_handler = RotatingFileHandler(
                LOG_FILE,
                maxBytes=MAX_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8"
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            logging.getLogger().addHandler(file_handler)
        except Exception as e:
            print(f"[STTMeet] WARNING: Could not create log file at {LOG_FILE}: {e}", file=sys.stderr)

        # --- Console handler (INFO and above) ---
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logging.getLogger().addHandler(console_handler)

        logging.getLogger().setLevel(logging.DEBUG)
        _initialized = True

    return logger
