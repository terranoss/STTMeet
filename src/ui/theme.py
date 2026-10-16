"""
STTMeet UI Theme Constants
Shared color pairs so transparent widgets stay readable in both appearance
modes. CustomTkinter's default button text color (#DCE4EE) is designed for
filled buttons and washes out on transparent surfaces.
"""

TRANSPARENT_TEXT = ("#1F2937", "#E5E7EB")
TRANSPARENT_HOVER = ("#D4D4D8", "#3F3F46")
ON_ACCENT_TEXT = ("#FFFFFF", "#FFFFFF")

SIDEBAR_FG = ("#E2E8F0", "#1E293B")
SIDEBAR_BORDER = ("#CBD5E1", "#334155")
ACCENT_FG = ("#DBEAFE", "#1E3A5F")
ACCENT_HOVER = ("#BFDBFE", "#25476B")
ACCENT_TEXT = ("#1E3A8A", "#DBEAFE")
MUTED_TEXT = ("#475569", "#94A3B8")

TOOLBAR_BG = ("#F3F4F6", "#1F1F1F")
TOOLBAR_BORDER = ("#D1D5DB", "#3F3F46")
STATUS_BAR_BG = ("#ECECEC", "#2D2D2D")
STATUS_BAR_BORDER = ("#C0C0C0", "#404040")
BORDER_COLOR = ("#D1D5DB", "#3F3F46")


def center_window(window, parent=None, width=500, height=400):
    """Position a window centered over its parent, or centered on screen."""
    window.update_idletasks()
    if parent and hasattr(parent, "winfo_exists") and parent.winfo_exists():
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = max(0, px + (pw - width) // 2)
        y = max(0, py + (ph - height) // 2)
    else:
        sw = window.winfo_screenwidth()
        sh = window.winfo_screenheight()
        x = max(0, (sw - width) // 2)
        y = max(0, (sh - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")

