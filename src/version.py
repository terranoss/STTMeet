"""
STTMeet version information.

Single source of truth for the application version. The Windows build script
(scripts/build_windows.ps1) parses __version__ from this file and passes it to
Nuitka and Inno Setup, so bump it here before building an installer.
"""
from __future__ import annotations

__version__ = "1.0.0"


def get_app_version() -> str:
    """Return the application semantic version (e.g. '1.0.0')."""
    return __version__


def get_display_version() -> str:
    """Return the version as shown in the UI (e.g. 'v1.0.0')."""
    return f"v{__version__}"