"""
STTMeet Tooltip Component
Lightweight, theme-aware floating tooltips for Tkinter and CustomTkinter widgets.
"""
import tkinter as tk
from typing import Callable, Optional, Union
import customtkinter as ctk


class Tooltip:
    """
    Attaches a floating hover tooltip to any Tkinter or CustomTkinter widget.

    Supports dynamic text via a callable to reflect runtime locale changes.
    Matches CustomTkinter light/dark theme styling with crisp borders.
    """

    def __init__(
        self,
        widget: tk.Widget,
        text: Union[str, Callable[[], str]],
        delay_ms: int = 250,
        offset_y: int = 6
    ):
        self.widget = widget
        self.text_provider = text
        self.delay_ms = delay_ms
        self.offset_y = offset_y
        self.tip_window: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None

        self.widget.bind("<Enter>", self._on_enter, add="+")
        self.widget.bind("<Leave>", self._on_leave, add="+")
        self.widget.bind("<ButtonPress>", self._on_button_press, add="+")
        self.widget.bind("<Destroy>", self._on_destroy, add="+")

    def _get_text(self) -> str:
        if callable(self.text_provider):
            try:
                return str(self.text_provider())
            except Exception:
                return ""
        return str(self.text_provider)

    def _on_enter(self, _event=None):
        self._cancel_scheduled()
        if self.widget.winfo_exists():
            self._after_id = self.widget.after(self.delay_ms, self._show)

    def _on_leave(self, _event=None):
        self._cancel_scheduled()
        self._hide()

    def _on_button_press(self, _event=None):
        self._cancel_scheduled()
        self._hide()

    def _on_destroy(self, _event=None):
        self._cancel_scheduled()
        self._hide()

    def _cancel_scheduled(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        self._after_id = None
        tip_text = self._get_text().strip()
        if not tip_text or not self.widget.winfo_exists():
            return

        self._hide()

        try:
            x_root = self.widget.winfo_rootx()
            y_root = self.widget.winfo_rooty()
            w_widget = self.widget.winfo_width()
            h_widget = self.widget.winfo_height()
        except Exception:
            return

        # Theme-aware colors
        is_dark = ctk.get_appearance_mode().lower() == "dark"
        bg_color = "#18181B" if is_dark else "#FFFFFF"
        text_color = "#F4F4F5" if is_dark else "#18181B"
        border_color = "#3F3F46" if is_dark else "#CBD5E1"

        tw = tk.Toplevel(self.widget)
        self.tip_window = tw
        tw.wm_overrideredirect(True)
        try:
            tw.wm_attributes("-topmost", True)
        except Exception:
            pass

        # Container frame with fine border
        outer = tk.Frame(
            tw,
            background=border_color,
            padx=1,
            pady=1
        )
        outer.pack(fill="both", expand=True)

        inner = tk.Frame(
            outer,
            background=bg_color,
            padx=8,
            pady=4
        )
        inner.pack(fill="both", expand=True)

        lbl = tk.Label(
            inner,
            text=tip_text,
            justify=tk.LEFT,
            background=bg_color,
            foreground=text_color,
            font=("Segoe UI", 9)
        )
        lbl.pack()

        tw.update_idletasks()
        tip_w = tw.winfo_width()
        tip_h = tw.winfo_height()

        # Center horizontally under the widget, guard against screen boundaries
        screen_w = tw.winfo_screenwidth()
        screen_h = tw.winfo_screenheight()

        target_x = x_root + (w_widget // 2) - (tip_w // 2)
        target_y = y_root + h_widget + self.offset_y

        if target_x < 8:
            target_x = 8
        elif target_x + tip_w > screen_w - 8:
            target_x = screen_w - tip_w - 8

        # Flip above if too close to bottom edge
        if target_y + tip_h > screen_h - 10:
            target_y = y_root - tip_h - self.offset_y

        tw.wm_geometry(f"+{target_x}+{target_y}")

    def _hide(self):
        if self.tip_window is not None:
            try:
                self.tip_window.destroy()
            except Exception:
                pass
            self.tip_window = None
