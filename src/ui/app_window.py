"""
STTMeet GUI Application Window
Modern Desktop UI built with CustomTkinter.
Features:
- Slide-in hamburger menu: Settings (API Key), Save Session, Log folder, About
- Settings modal: API Key configuration & verification, FFmpeg check
- Audio File Picker with duration, size, and cost estimation
- Language Selection (Bahasa Melayu, English, Bilingual)
- Chunking controls & Audio Pre-processing toggle
- Live chunk-by-chunk progress bar & status updates
- Threaded execution with non-freezing UI and Cancel capability
- Tabbed view: Transcript, Summary, Meeting Minutes, Action Items
- Dynamic Speaker Mapping panel
- Multi-format Export: Word (.docx), Markdown (.md), Plain Text (.txt)
"""
import os
import sys
import json
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

from ..config import (
    get_api_key,
    save_api_key,
    BASE_DIR,
    CACHE_DIR,
    CHUNKS_DIR,
    DEFAULT_CHUNK_MINUTES,
    ENV_PATH,
    MODEL_NAME,
    MINUTES_MODEL_NAME
)
from ..logger import LOG_FILE, get_logger
from ..i18n import (
    ALL_MODES,
    DEFAULT_LOCALE,
    MINUTES_LANG_BY_UI_LOCALE,
    display_minutes_lang,
    mode_label,
    normalize_locale,
    translate,
)
from ..prefs import get_pref, save_pref
from .. import i18n as translate_module

log = get_logger(__name__)
from ..utils import (
    check_ffmpeg,
    get_audio_duration,
    format_duration,
    estimate_cost_and_tokens
)
from ..audio_processor import (
    preprocess_audio,
    split_audio_into_chunks,
    compute_file_hash
)
from ..gemini_transcriber import (
    get_gemini_client,
    transcribe_audio_chunk
)
from ..transcript_processor import (
    adjust_chunk_timestamps,
    deduplicate_overlap,
    extract_speakers,
    apply_speaker_mapping
)
from ..minutes_generator import (
    generate_meeting_minutes,
    parse_minutes_sections
)
from ..exporter import (
    export_to_docx,
    export_to_markdown,
    export_to_text
)
from ..session_store import (
    build_session_payload,
    load_session,
    normalize_settings,
    save_session,
    session_path
)
from ..version import get_display_version

# Set UI Theme
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

# CustomTkinter resolves a button's text colour to a fixed light value when
# fg_color="transparent", regardless of appearance mode, which makes the glyph
# invisible on the light-theme surface. Text and hover colours for such buttons
# are therefore always set explicitly as (light, dark) tuples.
TRANSPARENT_TEXT = ("#1F2937", "#E5E7EB")
TRANSPARENT_HOVER = ("#D4D4D8", "#3F3F46")
ON_ACCENT_TEXT = ("#FFFFFF", "#FFFFFF")

# The dashboard opens maximized. CustomTkinter runs a DPI scaling pass shortly
# after startup that re-applies self.geometry() and undoes state("zoomed"), so
# the zoomed state is re-asserted for a couple of seconds before the window is
# handed over to the user.
_MAXIMIZE_POLL_MS = 300
_MAXIMIZE_RETRY_COUNT = 8

class ChunkMonitorDialog(ctk.CTkToplevel):
    """
    Floating dialog panel displaying live status for each audio chunk.
    Enables users to monitor pending/working/done/error states, cancel execution,
    reprocess failed chunks individually, and extract all combined transcripts.
    """
    def __init__(self, master, chunks_meta: List[Dict], on_cancel_callback, on_reprocess_callback, on_extract_callback,
                 t: Optional[Callable[..., str]] = None):
        super().__init__(master)
        self.master_app = master
        self.chunks_meta = chunks_meta
        self.on_cancel_callback = on_cancel_callback
        self.on_reprocess_callback = on_reprocess_callback
        self.on_extract_callback = on_extract_callback

        # Translation callable supplied by the main window so this dialog follows
        # language switches. Falls back to English-only if none is given.
        self._t = t or (lambda key, **fmt: translate(key, "en", **fmt))
        self._i18n: List[Tuple[Any, str]] = []
        self._chunk_detail: Dict[int, str] = {}  # chunk index -> last error detail

        self.title(self._t("monitor.title"))
        self.geometry("640x520")
        self.minsize(550, 400)
        self.transient(master)

        self.row_widgets: Dict[int, Dict] = {}
        self._build_ui()

    def _label(self, widget, key: str, **fmt):
        self._i18n.append((widget, key))
        widget.configure(text=self._t(key, **fmt))
        return widget

    def retranslate(self):
        """Re-apply every string after the app's language changes."""
        for widget, resolver in self._i18n:
            try:
                if not widget.winfo_exists():
                    continue
                widget.configure(text=resolver(self._t) if callable(resolver) else self._t(resolver))
            except Exception:
                continue
        # Badges carry state-dependent text, so re-render from stored state.
        for chunk_index, widgets in self.row_widgets.items():
            state = widgets.get("state", "pending")
            self.update_chunk_state(chunk_index, state, self._chunk_detail.get(chunk_index, ""))
        if getattr(self, "_last_summary_args", None):
            self.update_overall_summary(*self._last_summary_args)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header Info Card
        header_frame = ctk.CTkFrame(self, corner_radius=8)
        header_frame.grid(row=0, column=0, padx=14, pady=(12, 6), sticky="ew")
        header_frame.grid_columnconfigure(0, weight=1)

        self.summary_label = ctk.CTkLabel(
            header_frame,
            text=self._t("monitor.header", total=len(self.chunks_meta)),
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.summary_label.grid(row=0, column=0, padx=12, pady=(10, 4), sticky="w")

        self.progress_bar = ctk.CTkProgressBar(header_frame)
        self.progress_bar.grid(row=1, column=0, padx=12, pady=(2, 10), sticky="ew")
        self.progress_bar.set(0.0)

        # Scrollable Chunk List
        self.scroll_frame = ctk.CTkScrollableFrame(self, corner_radius=8)
        self.scroll_frame.grid(row=1, column=0, padx=14, pady=6, sticky="nsew")
        self.scroll_frame.grid_columnconfigure(1, weight=1)

        for i, chunk in enumerate(self.chunks_meta):
            idx = chunk["chunk_index"]
            start_sec = chunk.get("start_ms", 0) / 1000.0
            end_sec = chunk.get("end_ms", 0) / 1000.0
            time_str = f"{format_duration(start_sec)} - {format_duration(end_sec)}"

            card = ctk.CTkFrame(self.scroll_frame, corner_radius=6, fg_color=("#F5F5F5", "#242424"))
            card.pack(fill="x", pady=4, padx=4)
            card.grid_columnconfigure(1, weight=1)

            lbl_title = ctk.CTkLabel(
                card,
                text=self._t("monitor.chunk_title", index=i + 1, time=time_str),
                font=ctk.CTkFont(size=12, weight="bold"),
                width=200,
                anchor="w"
            )
            lbl_title.grid(row=0, column=0, padx=(10, 6), pady=8, sticky="w")
            self._i18n.append(
                (lbl_title, lambda i=i + 1, ts=time_str: self._t("monitor.chunk_title", index=i, time=ts))
            )

            badge = ctk.CTkLabel(
                card,
                text=self._t("monitor.state_pending"),
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="gray",
                fg_color=("#E0E0E0", "#2B2B2B"),
                corner_radius=6,
                padx=10,
                pady=3
            )
            badge.grid(row=0, column=1, padx=6, pady=8, sticky="w")

            btn_reprocess = ctk.CTkButton(
                card,
                text=self._t("monitor.reprocess"),
                width=100,
                height=26,
                font=ctk.CTkFont(size=11),
                fg_color="#D32F2F",
                hover_color="#B71C1C",
                state="disabled",
                command=lambda c_idx=idx: self.on_reprocess_callback(c_idx)
            )
            btn_reprocess.grid(row=0, column=2, padx=(6, 10), pady=8, sticky="e")
            self._i18n.append((btn_reprocess, "monitor.reprocess"))

            self.row_widgets[idx] = {
                "card": card,
                "badge": badge,
                "btn_reprocess": btn_reprocess,
                "state": "pending",
            }

        # Bottom Action Bar
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.grid(row=2, column=0, padx=14, pady=(6, 12), sticky="ew")
        bottom_frame.grid_columnconfigure(1, weight=1)

        self.btn_cancel = ctk.CTkButton(
            bottom_frame,
            text=self._t("monitor.cancel"),
            fg_color="#C62828",
            hover_color="#B71C1C",
            width=100,
            command=self.on_cancel_callback
        )
        self.btn_cancel.grid(row=0, column=0, padx=(0, 6), pady=6, sticky="w")
        self._i18n.append((self.btn_cancel, "monitor.cancel"))

        self.btn_extract = ctk.CTkButton(
            bottom_frame,
            text=self._t("monitor.extract"),
            fg_color="#2E7D32",
            hover_color="#1B5E20",
            font=ctk.CTkFont(weight="bold"),
            width=170,
            state="disabled",
            command=self.on_extract_callback
        )
        self.btn_extract.grid(row=0, column=2, padx=6, pady=6, sticky="e")
        self._i18n.append((self.btn_extract, "monitor.extract"))

        self.btn_close = ctk.CTkButton(
            bottom_frame,
            text=self._t("monitor.hide"),
            width=100,
            command=self.withdraw
        )
        self.btn_close.grid(row=0, column=3, padx=(6, 0), pady=6, sticky="e")
        self._i18n.append((self.btn_close, "monitor.hide"))

    def update_chunk_state(self, chunk_index: int, state: str, detail: str = ""):
        """
        Updates visual badge and buttons for a chunk.
        state: 'pending', 'working', 'done', 'error', 'cancelled'
        """
        widgets = self.row_widgets.get(chunk_index)
        if not widgets:
            return

        badge = widgets["badge"]
        btn_reprocess = widgets["btn_reprocess"]
        widgets["state"] = state
        self._chunk_detail[chunk_index] = detail

        states_config = {
            "pending": (self._t("monitor.state_pending"), "gray", ("#E0E0E0", "#2B2B2B"), "disabled"),
            "working": (self._t("monitor.state_working"), "#1976D2", ("#BBDEFB", "#0D47A1"), "disabled"),
            "done": (self._t("monitor.state_done"), "#2E7D32", ("#C8E6C9", "#1B5E20"), "disabled"),
            "error": (
                self._t("monitor.state_error_detail", detail=detail[:25]) if detail
                else self._t("monitor.state_error"),
                "#C62828", ("#FFCDD2", "#B71C1C"), "normal"
            ),
            "cancelled": (self._t("monitor.state_cancelled"), "gray", ("#E0E0E0", "#2B2B2B"), "normal"),
        }

        text, fg_col, bg_col, btn_state = states_config.get(state, states_config["pending"])
        badge.configure(text=text, text_color=fg_col, fg_color=bg_col)
        btn_reprocess.configure(state=btn_state)

    def update_overall_summary(self, completed_count: int, total_count: int, has_errors: bool = False):
        pct = (completed_count / total_count) if total_count > 0 else 0.0
        self.progress_bar.set(pct)
        self._last_summary_args = (completed_count, total_count, has_errors)

        status_text = self._t("monitor.summary_base", done=completed_count, total=total_count)
        if completed_count == total_count:
            status_text += self._t("monitor.summary_all_done")
            self.btn_extract.configure(state="normal")
            self.btn_cancel.configure(state="disabled")
        elif has_errors:
            status_text += self._t("monitor.summary_errors")
            self.btn_extract.configure(state="disabled")
        else:
            self.btn_extract.configure(state="disabled")

        self.summary_label.configure(text=status_text)


class STTMeetApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.ui_locale: str = normalize_locale(get_pref("ui_locale", DEFAULT_LOCALE))
        self._i18n_widgets: List[Tuple[Any, str]] = []  # (widget, i18n key)
        self._step_labels: Dict[str, str] = {}         # step key -> base label
        self._locale_buttons: Dict[str, Any] = {}

        # Minutes language is derived from the UI locale rather than edited by
        # the user. Values stay canonical: they are validated by
        # session_store.VALID_LANGUAGES and key the Gemini prompt table.
        self.lang_var = ctk.StringVar(value=MINUTES_LANG_BY_UI_LOCALE[self.ui_locale])

        self.title(self._t("window.title", version=get_display_version()))
        self.geometry("1100x820")
        self.minsize(950, 750)

        # Worker & State
        self.worker_thread: Optional[threading.Thread] = None
        self.cancel_event = threading.Event()
        self.is_processing = False

        # API Key lives here for the whole session; the entry widget only exists
        # inside the Settings modal. Seeded from .env so a restart restores it.
        self.api_key_var: ctk.StringVar = ctk.StringVar(value=get_api_key())

        self.selected_audio_file: Optional[str] = None
        self.audio_duration_seconds: float = 0.0
        self.raw_transcript: str = ""
        self.processed_transcript: str = ""
        self.generated_minutes: str = ""
        self.detected_speakers: List[str] = []
        self.speaker_entries: Dict[str, ctk.CTkEntry] = {}
        self.speaker_mapping: Dict[str, str] = {}

        # Chunk Monitor & State Tracking
        self.active_chunks_meta: List[Dict] = []
        self.active_chunk_status: Dict[int, Dict] = {}  # index -> {"status": ..., "text": ..., "error": ...}
        self.monitor_dialog = None
        self.active_client = None
        self.active_checkpoint_file = None
        self.active_file_hash: str = ""

        # Session bookkeeping. _step_states / _progress_value mirror the widgets so
        # autosaves from the worker thread never have to read Tk state.
        self._session_settings_snapshot: Optional[Dict] = None
        self._step_states = {"step1": "pending", "step2": "pending", "step3": "pending", "step4": "pending"}
        self._progress_value: float = 0.0

        # Slide-in menu (created lazily on first open)
        self._menu_open: bool = False
        self.menu_overlay = None
        self.menu_frame = None
        self.menu_key_badge = None
        self._menu_slide_job: Optional[str] = None

        self._build_ui()
        self._refresh_output_lang_chip()
        self._check_initial_environment()
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)
        self.bind("<Escape>", self._on_escape_key)
        self._start_maximized()

    def _start_maximized(self):
        """Open the dashboard maximized on the primary display.

        CustomTkinter's first DPI scaling pass re-applies the geometry passed to
        self.geometry() (CTk._set_scaling -> Tk.geometry()), which knocks a
        window that was maximized during __init__ straight back to 1100x820.
        So re-assert the zoomed state for a short while after startup, then stop
        and leave the window under the user's control.
        """
        self._maximize_retries_left = _MAXIMIZE_RETRY_COUNT
        self._maximize_once()

    def _maximize_once(self):
        """Apply the zoomed state, and keep retrying while retries remain."""
        try:
            self.update_idletasks()
            if self.state() != "zoomed":
                self.state("zoomed")
        except Exception:
            try:
                self.attributes("-zoomed", True)
            except Exception:
                return  # Give up; the 1100x820 geometry set above still applies.

        self._maximize_retries_left -= 1
        if self._maximize_retries_left > 0:
            self.after(_MAXIMIZE_POLL_MS, self._maximize_once)

    def _build_ui(self):
        # Master Grid Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # 1. Top Section: Header & Settings
        self._build_header_and_settings()

        # 2. File Selection & Audio Details Card
        self._build_file_section()

        # 3. Action Controls & Progress
        self._build_controls_section()

        # 4. Center Section: Tabbed Content Viewer
        self._build_tabs_section()

        # 5. Bottom Section: Speaker Mapping & Export Bar
        self._build_bottom_bar()

    # -------------------------------------------------------------
    # Localization
    # -------------------------------------------------------------
    def _t(self, key: str, **fmt) -> str:
        """Translate a UI string in the active locale."""
        return translate(key, self.ui_locale, **fmt)

    def _i18n_label(self, widget, key: str, **fmt):
        """
        Register a widget for live re-translation and set its initial text.

        Used at every construction site so no label can be missed by a switch.
        """
        self._i18n_widgets.append((widget, key))
        widget.configure(text=self._t(key, **fmt))
        return widget

    def _set_ui_locale(self, locale: str):
        """Switch UI language, cascade the output language, and re-label everything."""
        locale = normalize_locale(locale)
        if locale == self.ui_locale:
            self._refresh_locale_toggle()
            return

        self.ui_locale = locale
        save_pref("ui_locale", locale)
        self._cascade_minutes_lang()
        self._retranslate_ui()
        self._refresh_locale_toggle()
        self._refresh_output_lang_chip()
        self._set_status(self._t("status.ready"))

    def _cascade_minutes_lang(self):
        """
        Derive lang_var from the UI locale.

        lang_var is no longer user-editable: its values are validated by
        session_store.VALID_LANGUAGES and used as keys to pick a Gemini prompt,
        so the UI locale is the single source of truth.
        """
        self.lang_var.set(MINUTES_LANG_BY_UI_LOCALE[self.ui_locale])

    def _refresh_output_lang_chip(self):
        """Update the read-only chip that shows which language minutes use."""
        chip_var = getattr(self, "_output_lang_var", None)
        if chip_var is None:
            return
        # In combined mode the chip label already carries both languages, so the
        # value stays a single name instead of expanding to "Bilingual / Dwibahasa".
        value_locale = "en" if self.ui_locale == "both" else self.ui_locale
        display = display_minutes_lang(self.lang_var.get(), value_locale)
        chip_var.set(self._t("control.output_lang", value=display))

    def _open_menu_for_language(self):
        """Open the drawer so the language toggle is reachable from the chip."""
        self._open_menu()
        try:
            self.menu_frame.lift()
        except Exception:
            pass

    def _retranslate_ui(self):
        """Re-apply every registered string plus the widgets with custom logic."""
        for item in self._i18n_widgets:
            try:
                if len(item) == 3:
                    widget, key, fmt_fn = item
                    if not widget.winfo_exists():
                        continue
                    widget.configure(text=fmt_fn(self._t(key)))
                else:
                    widget, key = item
                    if not widget.winfo_exists():
                        continue
                    widget.configure(text=self._t(key))
            except Exception:
                # A dialog closed since registration; nothing to update.
                continue

        self._retranslate_tabs()
        self._retranslate_steps()
        self._refresh_locale_toggle()
        if self.monitor_dialog is not None and self.monitor_dialog.winfo_exists():
            try:
                self.monitor_dialog.retranslate()
            except Exception:
                log.warning("Could not retranslate chunk monitor", exc_info=True)

    def _retranslate_tabs(self):
        """
        Re-label the tab buttons.

        CTkTabview.rename() changes the tab's identity, not its visible text, so
        the segmented button's buttons_dict is updated directly. Tabs are created
        under locale-independent names, so this only touches the caption.
        """
        for internal, key in (
            ("tab_transcript", "tab.transcript"),
            ("tab_minutes", "tab.minutes"),
            ("tab_summary", "tab.summary"),
            ("tab_actions", "tab.actions"),
        ):
            try:
                button = self.tabview._segmented_button._buttons_dict.get(internal)
                if button is not None:
                    button.configure(text=self._t(key))
            except Exception:
                pass  # Private API unavailable; leave captions as-is.

    def _retranslate_steps(self):
        """Re-render step badges with labels in the new language."""
        for s_idx, (s_key, s_i18n) in enumerate(
            [("step1", "step.step1"), ("step2", "step.step2"),
             ("step3", "step.step3"), ("step4", "step.step4")]
        ):
            self._step_labels[s_key] = self._t(s_i18n)
            badge = self.step_badges.get(s_key)
            if badge is None or not badge.winfo_exists():
                continue
            state = self._step_states.get(s_key, "pending")
            icons = {"pending": "⚪", "working": "🔵", "done": "🟢", "error": "🔴"}
            badge.configure(text=f"{self._step_labels[s_key]} {icons.get(state, '⚪')}")

    def _audit_untranslated(self) -> List[str]:
        """
        Dev helper: report labelled widgets whose text is not in the i18n table.
        Returns a list of human-readable findings.

        Skips widgets whose text comes from a StringVar (cget returns the widget
        default for those) and icon-only labels like the hamburger glyph.
        """
        known = set()
        for entry in translate_module.STRINGS.values():
            known.update(v for v in entry.values())
            # The combined mode renders an auto-joined string that is not stored
            # verbatim, so include the rendered form to avoid false positives.
            known.add(translate_module._resolve_mode(entry, "both"))
            known.add(translate_module._resolve_mode(entry, "en"))
            known.add(translate_module._resolve_mode(entry, "ms"))
        known.update(translate_module.MODE_NAMES.values())
        found = []
        for widget in self.winfo_children():
            for child in widget.winfo_children():
                if not isinstance(child, (ctk.CTkLabel, ctk.CTkButton)):
                    continue
                try:
                    text = child.cget("text")
                    textvariable = child.cget("textvariable")
                except Exception:
                    continue
                if textvariable is not None:
                    continue
                if not isinstance(text, str) or text in known:
                    continue
                # Icon-only buttons (☰, etc.) have nothing to translate.
                if not any(ch.isalnum() for ch in text):
                    continue
                found.append(text)
        return found

    def _build_header_and_settings(self):
        top_frame = ctk.CTkFrame(self, corner_radius=10)
        top_frame.grid(row=0, column=0, padx=16, pady=(12, 6), sticky="ew")
        top_frame.grid_columnconfigure(2, weight=1)

        # Hamburger toggle — opens the slide-in menu
        self.menu_btn = ctk.CTkButton(
            top_frame,
            text="☰",
            width=42,
            font=ctk.CTkFont(size=20),
            fg_color="transparent",
            text_color=TRANSPARENT_TEXT,
            hover_color=TRANSPARENT_HOVER,
            command=self._toggle_menu
        )
        self.menu_btn.grid(row=0, column=0, padx=(10, 6), pady=10, sticky="w")

        title_label = ctk.CTkLabel(
            top_frame,
            text=self._t("header.title"),
            font=ctk.CTkFont(size=20, weight="bold")
        )
        title_label.grid(row=0, column=1, padx=(4, 10), pady=10, sticky="w")

        # Status Badges
        self.ffmpeg_badge = ctk.CTkLabel(
            top_frame,
            text=self._t("ffmpeg.checking"),
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.ffmpeg_badge.grid(row=0, column=3, padx=(10, 16), pady=10, sticky="e")

    # -------------------------------------------------------------
    # Slide-in Menu
    # -------------------------------------------------------------
    MENU_WIDTH = 300
    _MENU_SLIDE_STEPS = 6

    def _toggle_menu(self):
        if self._menu_open:
            self._close_menu()
        else:
            self._open_menu()

    def _on_escape_key(self, event=None):
        if self._menu_open:
            self._close_menu()
            return "break"
        return None

    def _open_menu(self):
        if self._menu_open:
            return
        self._menu_open = True
        self._cancel_menu_slide()

        if self.menu_overlay is None or not self.menu_overlay.winfo_exists():
            # A stipple-filled Tk Canvas is used as the dim layer: CustomTkinter's
            # colour parser rejects 8-digit #RRGGBBAA alpha values, so the 50%
            # dither pattern is the portable way to darken the content behind.
            self.menu_overlay = tk.Canvas(
                self,
                highlightthickness=0,
                bd=0
            )
            self.menu_overlay.create_rectangle(
                0, 0, 10000, 10000,
                fill="#000000",
                stipple="gray50",
                outline=""
            )
            self.menu_overlay.bind("<Button-1>", lambda _e: self._close_menu())
            self.menu_overlay.bind("<Escape>", self._on_escape_key)
        self.menu_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        # tkraise() on a Canvas is a tag operation, so raise the widget explicitly.
        self.tk.call("raise", self.menu_overlay._w)

        if self.menu_frame is None or not self.menu_frame.winfo_exists():
            self._build_menu_panel()
        self._refresh_menu_key_badge()
        self.menu_frame.place_configure(y=0, relheight=1)
        self.menu_frame.tkraise()

        # Slide in from the left edge
        self._animate_menu(target_x=0)

    def _close_menu(self, animate: bool = True):
        if not self._menu_open:
            return
        self._menu_open = False
        self._cancel_menu_slide()
        if not animate:
            if self.menu_frame is not None and self.menu_frame.winfo_exists():
                self.menu_frame.place_configure(x=-self._menu_width())
            self._teardown_menu_overlay()
        else:
            self._animate_menu(target_x=-self._menu_width(), then=self._teardown_menu_overlay)

    def _teardown_menu_overlay(self):
        """Remove the dimming overlay once the drawer is fully off-screen."""
        if self._menu_open:
            return
        if self.menu_overlay is not None and self.menu_overlay.winfo_exists():
            self.menu_overlay.place_forget()

    def _menu_width(self) -> int:
        """Actual on-screen width of the drawer, falling back to MENU_WIDTH."""
        if self.menu_frame is not None and self.menu_frame.winfo_exists():
            width = self.menu_frame.winfo_width()
            if width > 1:
                return width
        return self.MENU_WIDTH

    def _cancel_menu_slide(self):
        if self._menu_slide_job is not None:
            try:
                self.after_cancel(self._menu_slide_job)
            except Exception:
                pass
            self._menu_slide_job = None

    def _animate_menu(self, target_x: int, then=None):
        """Step the drawer horizontally toward target_x to fake a slide."""
        self._cancel_menu_slide()
        if self.menu_frame is None or not self.menu_frame.winfo_exists():
            if then:
                then()
            return

        try:
            current_x = int(self.menu_frame.winfo_x())
        except Exception:
            current_x = -self.MENU_WIDTH

        diff = target_x - current_x
        if abs(diff) <= 25:
            new_x = target_x
        else:
            raw_step = int(diff / 2.5)
            if diff > 0:
                step = max(raw_step, 60)
            else:
                step = min(raw_step, -60)
            new_x = current_x + step

        if (target_x > current_x and new_x >= target_x) or (target_x < current_x and new_x <= target_x):
            new_x = target_x

        self.menu_frame.place_configure(x=new_x)

        if new_x == target_x:
            self._menu_slide_job = None
            if then:
                self.after(0, then)
        else:
            self._menu_slide_job = self.after(16, self._animate_menu, target_x, then)

    def _build_menu_panel(self):
        self.menu_frame = ctk.CTkFrame(
            self,
            width=self.MENU_WIDTH,
            corner_radius=0,
            border_width=1,
            border_color=("gray80", "gray25")
        )
        self.menu_frame.grid_columnconfigure(0, weight=1)

        # Row 0: Top Header with App Title, version and Close '✕' button
        header_row = ctk.CTkFrame(self.menu_frame, fg_color="transparent")
        header_row.grid(row=0, column=0, padx=16, pady=(18, 6), sticky="ew")
        header_row.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(header_row, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")

        menu_title = ctk.CTkLabel(
            title_box,
            text=self._t("header.title"),
            font=ctk.CTkFont(size=18, weight="bold")
        )
        menu_title.pack(anchor="w")
        self._i18n_widgets.append((menu_title, "header.title"))

        menu_version = ctk.CTkLabel(
            title_box,
            text=get_display_version(),
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        menu_version.pack(anchor="w")

        close_btn = ctk.CTkButton(
            header_row,
            text="✕",
            width=28,
            height=28,
            corner_radius=14,
            fg_color="transparent",
            text_color=TRANSPARENT_TEXT,
            hover_color=TRANSPARENT_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._close_menu
        )
        close_btn.grid(row=0, column=1, sticky="e")

        # Row 1: Status Card
        status_card = ctk.CTkFrame(
            self.menu_frame,
            corner_radius=8,
            fg_color=("#F3F4F6", "#27272A"),
            border_width=1,
            border_color=("#E5E7EB", "#3F3F46")
        )
        status_card.grid(row=1, column=0, padx=14, pady=(6, 12), sticky="ew")
        status_card.grid_columnconfigure(0, weight=1)

        self.menu_key_badge = ctk.CTkLabel(
            status_card,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
            padx=10,
            pady=8
        )
        self.menu_key_badge.grid(row=0, column=0, sticky="ew")

        # Row 2 & 3: Language Toggle (Pill container)
        lang_label = ctk.CTkLabel(
            self.menu_frame,
            text=self._t("menu.language_label"),
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray40", "gray60"),
            anchor="w"
        )
        lang_label.grid(row=2, column=0, padx=18, pady=(2, 4), sticky="w")
        self._i18n_widgets.append((lang_label, "menu.language_label"))

        locale_container = ctk.CTkFrame(
            self.menu_frame,
            corner_radius=8,
            fg_color=("#E5E7EB", "#27272A"),
            border_width=1,
            border_color=("#D1D5DB", "#3F3F46")
        )
        locale_container.grid(row=3, column=0, padx=14, pady=(0, 14), sticky="ew")
        for i in range(len(ALL_MODES)):
            locale_container.grid_columnconfigure(i, weight=1)

        self._locale_buttons = {}
        for i, mode in enumerate(ALL_MODES):
            btn = ctk.CTkButton(
                locale_container,
                text=mode_label(mode, self.ui_locale),
                height=30,
                corner_radius=6,
                font=ctk.CTkFont(size=11),
                fg_color="transparent",
                text_color=TRANSPARENT_TEXT,
                hover_color=TRANSPARENT_HOVER,
                command=lambda m=mode: self._set_ui_locale(m)
            )
            btn.grid(row=0, column=i, padx=2, pady=2, sticky="ew")
            self._locale_buttons[mode] = btn
        self._refresh_locale_toggle()

        # Row 4: Section 1 Header - General
        sec_general = ctk.CTkLabel(
            self.menu_frame,
            text=self._t("menu.section_general"),
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("gray50", "gray55"),
            anchor="w"
        )
        sec_general.grid(row=4, column=0, padx=18, pady=(4, 2), sticky="w")
        self._i18n_widgets.append((sec_general, "menu.section_general"))

        # Row 5 & 6: General menu items
        self._add_menu_item("menu.settings", self._menu_action_settings, row=5, icon="⚙️")
        self._add_menu_item("menu.save_session", self._menu_action_save_session, row=6, icon="💾")

        # Row 7: Subtle divider line
        ctk.CTkFrame(self.menu_frame, height=1, fg_color=("gray85", "gray25")).grid(
            row=7, column=0, padx=18, pady=(8, 8), sticky="ew"
        )

        # Row 8: Section 2 Header - Tools & Info
        sec_tools = ctk.CTkLabel(
            self.menu_frame,
            text=self._t("menu.section_tools"),
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("gray50", "gray55"),
            anchor="w"
        )
        sec_tools.grid(row=8, column=0, padx=18, pady=(4, 2), sticky="w")
        self._i18n_widgets.append((sec_tools, "menu.section_tools"))

        # Row 9 & 10: Tools menu items
        self._add_menu_item("menu.open_log_folder", self._menu_action_open_log_folder, row=9, icon="📁")
        self._add_menu_item("menu.about", self._menu_action_about, row=10, icon="ℹ️")

        # Row 11: Spacer row configured with weight=1 to absorb extra height
        self.menu_frame.grid_rowconfigure(11, weight=1)

        # Row 12: Footer / Close hint
        hint = ctk.CTkLabel(
            self.menu_frame,
            text=self._t("menu.close_hint"),
            font=ctk.CTkFont(size=10),
            text_color="gray",
            wraplength=self.MENU_WIDTH - 40,
            justify="center",
            anchor="center"
        )
        hint.grid(row=12, column=0, padx=18, pady=(10, 16), sticky="ew")
        self._i18n_widgets.append((hint, "menu.close_hint"))

    def _add_menu_item(self, key: str, command, row: int, icon: str = ""):
        """Add a drawer row with smooth card hover styling and optional icon."""
        def fmt(text: str) -> str:
            return f"{icon}  {text}" if icon else text

        btn = ctk.CTkButton(
            self.menu_frame,
            text=fmt(self._t(key)),
            anchor="w",
            height=38,
            corner_radius=8,
            fg_color="transparent",
            text_color=TRANSPARENT_TEXT,
            hover_color=TRANSPARENT_HOVER,
            font=ctk.CTkFont(size=13),
            command=command
        )
        btn.grid(row=row, column=0, padx=14, pady=2, sticky="ew")
        self._i18n_widgets.append((btn, key, fmt))

    def _refresh_locale_toggle(self):
        """Highlight the active language button and re-label all three."""
        for mode, btn in getattr(self, "_locale_buttons", {}).items():
            if not btn.winfo_exists():
                continue
            active = (mode == self.ui_locale)
            btn.configure(
                text=mode_label(mode, self.ui_locale),
                fg_color=("#1976D2", "#1565C0") if active else "transparent",
                text_color=ON_ACCENT_TEXT if active else TRANSPARENT_TEXT,
                hover_color=("#1565C0", "#0D47A1") if active else TRANSPARENT_HOVER,
                font=ctk.CTkFont(size=11, weight="bold" if active else "normal"),
            )

    def _refresh_menu_key_badge(self):
        if self.menu_key_badge is None or not self.menu_key_badge.winfo_exists():
            return
        if self.api_key_var.get().strip():
            self.menu_key_badge.configure(
                text=self._t("menu.key_configured"),
                text_color=("#15803D", "#4ADE80"),
                fg_color="transparent"
            )
        else:
            self.menu_key_badge.configure(
                text=self._t("menu.key_missing"),
                text_color=("#DC2626", "#F87171"),
                fg_color="transparent"
            )

    # -------------------------------------------------------------
    # Menu Actions
    # -------------------------------------------------------------
    def _menu_action_settings(self):
        self._close_menu(animate=False)
        self._open_settings_dialog()

    def _menu_action_save_session(self):
        self._close_menu(animate=False)
        self._save_session_manually()

    def _menu_action_open_log_folder(self):
        self._close_menu(animate=False)
        folder = LOG_FILE.parent
        try:
            os.startfile(str(folder))
            self._set_status(self._t("status.log_opened", folder=folder))
        except Exception as e:
            log.warning("Could not open log folder: %s", e)
            messagebox.showinfo(self._t("msg.log_folder"), self._t("msg.log_folder_body", folder=folder))

    def _menu_action_about(self):
        self._close_menu(animate=False)
        self._open_about_dialog()

    def _open_settings_dialog(self):
        """Modal holding Gemini API Key entry and Audio Preprocessing options."""
        dialog = ctk.CTkToplevel(self)
        dialog.title(self._t("settings.title"))
        dialog.geometry("520x460")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        body = ctk.CTkFrame(dialog, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=18)
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            body,
            text=self._t("settings.heading"),
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w"
        ).grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(
            body,
            text=self._t("settings.help"),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            justify="left",
            anchor="w"
        ).grid(row=1, column=0, pady=(6, 12), sticky="ew")

        entry_row = ctk.CTkFrame(body, fg_color="transparent")
        entry_row.grid(row=2, column=0, sticky="ew")
        entry_row.grid_columnconfigure(0, weight=1)

        show_state = {"visible": False}
        key_entry = ctk.CTkEntry(
            entry_row,
            textvariable=self.api_key_var,
            show="•",
            placeholder_text=self._t("settings.placeholder")
        )
        key_entry.grid(row=0, column=0, sticky="ew")

        def close_dialog(_event=None):
            """Detach the entry's trace on the shared api_key_var, then close.

            CTkEntry registers a StringVar trace that its own destroy() never
            removes, which would leave a callback pointing at dead widgets.
            """
            trace = getattr(key_entry, "_textvariable_callback_name", "")
            if trace:
                try:
                    self.api_key_var.trace_remove("write", trace)
                except Exception:
                    pass
            dialog.destroy()

        def toggle_visibility():
            show_state["visible"] = not show_state["visible"]
            key_entry.configure(show="" if show_state["visible"] else "•")
            toggle_btn.configure(text="🙈" if show_state["visible"] else "👁")

        toggle_btn = ctk.CTkButton(
            entry_row,
            text="👁",
            width=42,
            command=toggle_visibility
        )
        toggle_btn.grid(row=0, column=1, padx=(6, 0))

        ctk.CTkLabel(
            body,
            text=self._t("settings.saved_to", path=str(ENV_PATH)),
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w"
        ).grid(row=3, column=0, pady=(6, 0), sticky="w")

        # Divider between API Key and Audio Preprocessing
        ctk.CTkFrame(body, height=1, fg_color=("gray85", "gray25")).grid(
            row=4, column=0, pady=(16, 12), sticky="ew"
        )

        # Audio Preprocessing Section
        ctk.CTkLabel(
            body,
            text=self._t("settings.audio_heading"),
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w"
        ).grid(row=5, column=0, sticky="ew")

        temp_preprocess_var = ctk.BooleanVar(value=bool(self.preprocess_var.get()))
        preprocess_chk = ctk.CTkCheckBox(
            body,
            text=self._t("settings.preprocess_chk"),
            variable=temp_preprocess_var,
            font=ctk.CTkFont(size=13, weight="bold")
        )
        preprocess_chk.grid(row=6, column=0, pady=(10, 4), sticky="w")

        ctk.CTkLabel(
            body,
            text=self._t("settings.preprocess_help"),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            justify="left",
            wraplength=470,
            anchor="w"
        ).grid(row=7, column=0, pady=(0, 6), sticky="ew")

        def do_save():
            if self._save_api_key(notify=False):
                new_prep = bool(temp_preprocess_var.get())
                self.preprocess_var.set(new_prep)
                save_pref("preprocess", new_prep)
                messagebox.showinfo(self._t("msg.success"), self._t("msg.key_saved_body"), parent=dialog)
                close_dialog()

        def do_clear():
            save_api_key("")
            close_dialog()
            self.api_key_var.set("")
            self._refresh_menu_key_badge()
            self._set_status(self._t("status.key_cleared"))
            messagebox.showinfo(self._t("msg.cleared"), self._t("msg.key_cleared_body"))

        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.grid(row=8, column=0, pady=(18, 0), sticky="ew")
        btn_row.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            btn_row, text=self._t("settings.clear"), width=110, fg_color=("#C62828", "#B71C1C"),
            hover_color=("#B71C1C", "#8E0000"), command=do_clear
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            btn_row, text=self._t("settings.cancel"), width=100, command=close_dialog
        ).grid(row=0, column=2, padx=6, sticky="e")
        ctk.CTkButton(
            btn_row, text=self._t("settings.save"), width=110, fg_color="#2E7D32", hover_color="#1B5E20",
            font=ctk.CTkFont(weight="bold"), command=do_save
        ).grid(row=0, column=3, sticky="e")

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        dialog.after(50, key_entry.focus_set)

    def _open_about_dialog(self):
        ffmpeg_ok, _ = check_ffmpeg()
        dialog = ctk.CTkToplevel(self)
        dialog.title(self._t("about.title"))
        dialog.geometry("480x420")
        dialog.resizable(False, False)
        dialog.transient(self)

        body = ctk.CTkFrame(dialog, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=18)
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            body, text=self._t("header.title"), font=ctk.CTkFont(size=20, weight="bold"), anchor="w"
        ).grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(
            body,
            text=f"{self._t('about.version', version=get_display_version())}\n{self._t('about.subtitle')}",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            justify="left",
            anchor="w"
        ).grid(row=1, column=0, pady=(4, 16), sticky="ew")

        rows = [
            (self._t("about.row_ffmpeg"),
             self._t("about.ffmpeg_installed") if ffmpeg_ok else self._t("about.ffmpeg_missing")),
            (self._t("about.row_transcript_model"), MODEL_NAME),
            (self._t("about.row_minutes_model"), MINUTES_MODEL_NAME),
            (self._t("about.row_data_folder"), str(BASE_DIR)),
            (self._t("about.row_cache"), str(CACHE_DIR)),
            (self._t("about.row_log"), str(LOG_FILE)),
        ]
        for idx, (label, value) in enumerate(rows, start=2):
            ctk.CTkLabel(
                body, text=label, font=ctk.CTkFont(size=11, weight="bold"), anchor="w"
            ).grid(row=idx, column=0, pady=(0, 8), sticky="w")
            ctk.CTkLabel(
                body, text=value, font=ctk.CTkFont(size=11), anchor="w", wraplength=280, justify="left"
            ).grid(row=idx, column=1, pady=(0, 8), sticky="w")
        body.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(body, text=self._t("about.close"), width=100, command=dialog.destroy).grid(
            row=len(rows) + 2, column=0, columnspan=2, pady=(18, 0), sticky="e"
        )

    def _build_file_section(self):
        file_frame = ctk.CTkFrame(self, corner_radius=10)
        file_frame.grid(row=1, column=0, padx=16, pady=6, sticky="ew")
        file_frame.grid_columnconfigure(1, weight=1)

        browse_btn = ctk.CTkButton(
            file_frame,
            text=self._t("file.select"),
            command=self._browse_audio_file,
            width=160,
            font=ctk.CTkFont(weight="bold")
        )
        browse_btn.grid(row=0, column=0, padx=16, pady=12, sticky="w")
        self._i18n_label(browse_btn, "file.select")

        self.file_label = ctk.CTkLabel(
            file_frame,
            text=self._t("file.no_selection"),
            anchor="w",
            font=ctk.CTkFont(size=13)
        )
        self.file_label.grid(row=0, column=1, padx=10, pady=12, sticky="ew")

        # Audio Info Row
        self.audio_stats_label = ctk.CTkLabel(
            file_frame,
            text=self._t("file.stats_placeholder"),
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.audio_stats_label.grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 10), sticky="w")

    def _build_controls_section(self):
        ctrl_frame = ctk.CTkFrame(self, corner_radius=10)
        ctrl_frame.grid(row=2, column=0, padx=16, pady=6, sticky="ew")
        ctrl_frame.grid_columnconfigure(2, weight=1)

        # Engine Selector
        engine_lbl = ctk.CTkLabel(ctrl_frame, text=self._t("control.engine"))
        engine_lbl.grid(row=0, column=0, padx=(16, 6), pady=10, sticky="w")
        self._i18n_label(engine_lbl, "control.engine")

        self.engine_var = ctk.StringVar(value="⚡ Gemini Cloud (Auto-Failover)")
        self.engine_dropdown = ctk.CTkOptionMenu(
            ctrl_frame,
            values=[
                "⚡ Gemini Cloud (Auto-Failover)",
                "☁️ Gemini 3 Flash",
                "☁️ Gemini 3.8 Flash",
                "☁️ Gemini 3.5 Flash",
                "☁️ Gemini 3.5 Flash Lite"
            ],
            variable=self.engine_var,
            width=230,
            command=self._on_engine_changed
        )
        self.engine_dropdown.grid(row=0, column=1, padx=6, pady=10, sticky="w")

        # Chunk Size Selector
        chunk_lbl = ctk.CTkLabel(ctrl_frame, text=self._t("control.chunk"))
        chunk_lbl.grid(row=0, column=2, padx=(16, 6), pady=10, sticky="w")
        self._i18n_label(chunk_lbl, "control.chunk")

        self.chunk_size_var = ctk.StringVar(value="25 min")
        self.chunk_dropdown = ctk.CTkOptionMenu(
            ctrl_frame,
            values=["15 min", "20 min", "25 min", "30 min", "45 min"],
            variable=self.chunk_size_var,
            width=90
        )
        self.chunk_dropdown.grid(row=0, column=3, padx=6, pady=10, sticky="w")

        # Pre-process state: persisted across restarts via prefs.json, edited in Settings modal
        self.preprocess_var = ctk.BooleanVar(value=bool(get_pref("preprocess", True)))

        # Action Buttons
        self.start_btn = ctk.CTkButton(
            ctrl_frame,
            text=self._t("btn.transcribe"),
            fg_color="#2E7D32",
            hover_color="#1B5E20",
            font=ctk.CTkFont(weight="bold"),
            command=self._start_processing_pipeline,
            width=150
        )
        self.start_btn.grid(row=0, column=4, padx=4, pady=10, sticky="e")
        self._i18n_label(self.start_btn, "btn.transcribe")

        # Read-only output-language chip. lang_var is derived from the UI locale,
        # so this shows the result rather than offering a second control.
        self._output_lang_var = ctk.StringVar()
        self.output_lang_chip = ctk.CTkButton(
            ctrl_frame,
            textvariable=self._output_lang_var,
            width=170,
            height=30,
            corner_radius=6,
            fg_color=("#E8EAF6", "#2A2A3D"),
            hover_color=("#C5CAE9", "#3A3A52"),
            font=ctk.CTkFont(size=11),
            text_color=("#3949AB", "#9FA8DA"),
            command=self._open_menu_for_language,
        )
        self.output_lang_chip.grid(row=0, column=5, padx=4, pady=10, sticky="e")

        self.gen_minutes_btn = ctk.CTkButton(
            ctrl_frame,
            text=self._t("btn.generate_minutes"),
            fg_color="#1976D2",
            hover_color="#1565C0",
            font=ctk.CTkFont(weight="bold"),
            command=self._start_minutes_generation_only,
            state="disabled",
            width=150
        )
        self.gen_minutes_btn.grid(row=0, column=6, padx=4, pady=10, sticky="e")
        self._i18n_label(self.gen_minutes_btn, "btn.generate_minutes")

        self.cancel_btn = ctk.CTkButton(
            ctrl_frame,
            text=self._t("btn.cancel"),
            fg_color="#C62828",
            hover_color="#B71C1C",
            command=self._cancel_processing,
            state="disabled",
            width=75
        )
        self.cancel_btn.grid(row=0, column=7, padx=4, pady=10, sticky="e")
        self._i18n_label(self.cancel_btn, "btn.cancel")

        self.monitor_btn = ctk.CTkButton(
            ctrl_frame,
            text=self._t("btn.monitor"),
            fg_color=("#455A64", "#37474F"),
            hover_color=("#37474F", "#263238"),
            font=ctk.CTkFont(weight="bold"),
            command=self._open_or_focus_chunk_monitor,
            state="disabled",
            width=130
        )
        self.monitor_btn.grid(row=0, column=8, padx=4, pady=10, sticky="e")
        self._i18n_label(self.monitor_btn, "btn.monitor")

        self.reset_btn = ctk.CTkButton(
            ctrl_frame,
            text=self._t("btn.reset"),
            fg_color=("#78909C", "#455A64"),
            hover_color=("#546E7A", "#37474F"),
            font=ctk.CTkFont(weight="bold"),
            command=self._reset_workspace,
            width=85
        )
        self.reset_btn.grid(row=0, column=9, padx=4, pady=10, sticky="e")
        self._i18n_label(self.reset_btn, "btn.reset")

        self.save_session_btn = ctk.CTkButton(
            ctrl_frame,
            text=self._t("btn.save_session"),
            fg_color=("#00897B", "#00695C"),
            hover_color=("#00796B", "#004D40"),
            font=ctk.CTkFont(weight="bold"),
            command=self._save_session_manually,
            state="disabled",
            width=130
        )
        self.save_session_btn.grid(row=0, column=10, padx=(4, 16), pady=10, sticky="e")
        self._i18n_label(self.save_session_btn, "btn.save_session")

        # Visual Stepper Bar
        self.stepper_frame = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        self.stepper_frame.grid(row=1, column=0, columnspan=12, padx=16, pady=(4, 4), sticky="ew")
        for col_idx in range(7):
            self.stepper_frame.grid_columnconfigure(col_idx, weight=1 if col_idx % 2 == 0 else 0)

        self.step_badges = {}
        steps_def = [
            ("step1", "step.step1"),
            ("step2", "step.step2"),
            ("step3", "step.step3"),
            ("step4", "step.step4"),
        ]

        for s_idx, (s_key, s_i18n) in enumerate(steps_def):
            grid_col = s_idx * 2
            self._step_labels[s_key] = self._t(s_i18n)
            badge = ctk.CTkLabel(
                self.stepper_frame,
                text=f"{self._step_labels[s_key]} ⚪",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="gray",
                fg_color=("#E0E0E0", "#2B2B2B"),
                corner_radius=6,
                padx=10,
                pady=3
            )
            badge.grid(row=0, column=grid_col, sticky="ew", padx=2)
            self.step_badges[s_key] = badge

            # Arrow between steps
            if s_idx < len(steps_def) - 1:
                arrow = ctk.CTkLabel(self.stepper_frame, text="➔", font=ctk.CTkFont(size=12), text_color="gray")
                arrow.grid(row=0, column=grid_col + 1, padx=2)

        # Progress bar & Status text
        self.progress_bar = ctk.CTkProgressBar(ctrl_frame)
        self.progress_bar.grid(row=2, column=0, columnspan=12, padx=16, pady=(4, 4), sticky="ew")
        self.progress_bar.set(0.0)

        self.status_label = ctk.CTkLabel(
            ctrl_frame,
            text=self._t("status.ready"),
            font=ctk.CTkFont(size=12),
            anchor="w"
        )
        self.status_label.grid(row=3, column=0, columnspan=12, padx=16, pady=(0, 10), sticky="w")

    def _build_tabs_section(self):
        self.tabview = ctk.CTkTabview(self, corner_radius=10)
        self.tabview.grid(row=3, column=0, padx=16, pady=6, sticky="nsew")

        # Tabs are added under locale-independent names so switching language
        # never changes tab identity; only the captions are re-labelled.
        self.tab_transcript = self.tabview.add("tab_transcript")
        self.tab_minutes = self.tabview.add("tab_minutes")
        self.tab_summary = self.tabview.add("tab_summary")
        self.tab_actions = self.tabview.add("tab_actions")
        self._retranslate_tabs()

        # Setup textboxes in each tab
        self.txt_transcript = self._create_textbox(self.tab_transcript)

        # Minutes tab with top inline retry banner
        self.tab_minutes.grid_columnconfigure(0, weight=1)
        self.tab_minutes.grid_rowconfigure(1, weight=1)

        self.minutes_banner_frame = ctk.CTkFrame(self.tab_minutes, fg_color=("#FFEBEE", "#421C1C"), corner_radius=6)
        self.minutes_banner_label = ctk.CTkLabel(
            self.minutes_banner_frame,
            text=self._t("minutes.banner_idle"),
            text_color=("#C62828", "#FFCDD2"),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.minutes_banner_label.pack(side="left", padx=12, pady=6)

        self.retry_minutes_btn = ctk.CTkButton(
            self.minutes_banner_frame,
            text=self._t("btn.retry_minutes"),
            fg_color="#D32F2F",
            hover_color="#B71C1C",
            width=140,
            command=self._start_minutes_generation_only
        )
        self.retry_minutes_btn.pack(side="right", padx=12, pady=6)
        self._i18n_label(self.retry_minutes_btn, "btn.retry_minutes")
        # Note: self.minutes_banner_frame starts hidden (not gridded until error occurs)

        self.txt_minutes = ctk.CTkTextbox(self.tab_minutes, wrap="word", font=ctk.CTkFont(family="Consolas", size=12))
        self.txt_minutes.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)

        self.txt_summary = self._create_textbox(self.tab_summary)
        self.txt_actions = self._create_textbox(self.tab_actions)

    def _create_textbox(self, parent_tab):
        parent_tab.grid_columnconfigure(0, weight=1)
        parent_tab.grid_rowconfigure(0, weight=1)
        tb = ctk.CTkTextbox(parent_tab, wrap="word", font=ctk.CTkFont(family="Consolas", size=12))
        tb.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        return tb

    def _build_bottom_bar(self):
        bottom_frame = ctk.CTkFrame(self, corner_radius=10)
        bottom_frame.grid(row=4, column=0, padx=16, pady=(6, 12), sticky="ew")
        bottom_frame.grid_columnconfigure(1, weight=1)

        # Speaker mapping trigger
        speaker_btn = ctk.CTkButton(
            bottom_frame,
            text=self._t("btn.map_speakers"),
            command=self._open_speaker_mapping_dialog,
            width=160
        )
        speaker_btn.grid(row=0, column=0, padx=16, pady=10, sticky="w")
        self._i18n_label(speaker_btn, "btn.map_speakers")

        # Export Buttons
        export_docx_btn = ctk.CTkButton(
            bottom_frame,
            text=self._t("btn.export_docx"),
            command=lambda: self._export_document("docx"),
            width=150
        )
        export_docx_btn.grid(row=0, column=2, padx=4, pady=10)
        self._i18n_label(export_docx_btn, "btn.export_docx")

        export_md_btn = ctk.CTkButton(
            bottom_frame,
            text=self._t("btn.export_md"),
            command=lambda: self._export_document("md"),
            width=150
        )
        export_md_btn.grid(row=0, column=3, padx=4, pady=10)
        self._i18n_label(export_md_btn, "btn.export_md")

        export_txt_btn = ctk.CTkButton(
            bottom_frame,
            text=self._t("btn.export_txt"),
            command=lambda: self._export_document("txt"),
            width=130
        )
        export_txt_btn.grid(row=0, column=4, padx=4, pady=10)
        self._i18n_label(export_txt_btn, "btn.export_txt")

        export_all_btn = ctk.CTkButton(
            bottom_frame,
            text=self._t("btn.export_all"),
            fg_color="#1565C0",
            hover_color="#0D47A1",
            command=lambda: self._export_document("all"),
            width=110
        )
        export_all_btn.grid(row=0, column=5, padx=(4, 16), pady=10)
        self._i18n_label(export_all_btn, "btn.export_all")

    # -------------------------------------------------------------
    # Helpers & Validation
    # -------------------------------------------------------------
    def _check_initial_environment(self):
        is_ok, msg = check_ffmpeg()
        if is_ok:
            self.ffmpeg_badge.configure(text=self._t("ffmpeg.installed"), text_color="#2E7D32")
        else:
            self.ffmpeg_badge.configure(text=self._t("ffmpeg.missing"), text_color="#C62828")
            messagebox.showwarning(
                self._t("msg.ffmpeg_warning"),
                self._t("msg.ffmpeg_missing_body")
            )

    def _save_api_key(self, notify: bool = True) -> bool:
        """Persist self.api_key_var to .env. Returns True when a key was saved."""
        new_key = self.api_key_var.get().strip()
        if not new_key:
            messagebox.showwarning(self._t("msg.warning"), self._t("msg.key_invalid"))
            return False
        save_api_key(new_key)
        self._refresh_menu_key_badge()
        self._set_status(self._t("status.key_saved"))
        if notify:
            messagebox.showinfo(self._t("msg.success"), self._t("msg.key_saved_env"))
        return True

    def _browse_audio_file(self):
        filetypes = [
            (self._t("filepicker.supported"), "*.mp3 *.m4a *.wav *.aac *.ogg *.flac *.mp4"),
            (self._t("filepicker.all"), "*.*")
        ]
        chosen = filedialog.askopenfilename(
            title=self._t("filepicker.audio_title"), filetypes=filetypes
        )
        if not chosen:
            return

        self.selected_audio_file = chosen
        file_name = Path(chosen).name
        file_size_mb = os.path.getsize(chosen) / (1024 * 1024)

        try:
            self.audio_duration_seconds = get_audio_duration(chosen)
            cost_info = estimate_cost_and_tokens(self.audio_duration_seconds)

            self.file_label.configure(text=self._t("file.selected", name=file_name))
            self.audio_stats_label.configure(
                text=self._t(
                    "file.stats",
                    duration=cost_info['formatted_duration'],
                    size=f"{file_size_mb:.1f}",
                    tokens=f"{cost_info['estimated_input_tokens']:,}",
                    cost=f"{cost_info['estimated_cost_usd']:.2f}",
                )
            )
        except Exception as e:
            self.file_label.configure(text=self._t("file.selected", name=file_name))
            self.audio_stats_label.configure(text=self._t("file.stats_error", error=e))

        # A valid file is now loaded: the session can be saved even if none exists yet
        self._set_save_session_enabled(True)

        # Auto-restore previous completed session if exists
        self._load_full_session_if_exists(chosen)

    def _get_selected_model_override(self) -> Optional[str]:
        """Returns the specific Gemini model string if selected, or None for Auto-Failover."""
        choice = self.engine_var.get()
        if "Flash Lite" in choice:
            return "gemini-3.5-flash-lite"
        elif "3.8 Flash" in choice:
            return "gemini-3.8-flash"
        elif "3.5 Flash" in choice:
            return "gemini-3.5-flash"
        elif "3 Flash" in choice:
            return "gemini-3-flash"
        return None

    def _on_engine_changed(self, choice: str):
        self.chunk_size_var.set("25 min")
        self.chunk_dropdown.configure(values=["15 min", "20 min", "25 min", "30 min", "45 min"])
        if "Auto" in choice:
            self._set_status(self._t("status.engine_auto"))
        else:
            self._set_status(self._t("status.engine_selected", choice=choice.strip()))

    # -------------------------------------------------------------
    # Processing Pipeline (Threaded)
    # -------------------------------------------------------------
    def _start_processing_pipeline(self):
        if not self.selected_audio_file or not os.path.exists(self.selected_audio_file):
            messagebox.showerror(self._t("msg.error"), self._t("msg.no_audio"))
            return

        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showerror(self._t("msg.error"), self._t("msg.key_required"))
            return

        self.is_processing = True
        self.cancel_event.clear()
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress_bar.set(0.0)
        self._reset_all_step_badges()
        self._session_settings_snapshot = None

        # Clear text displays
        for tb in [self.txt_transcript, self.txt_minutes, self.txt_summary, self.txt_actions]:
            tb.delete("1.0", "end")

        chunk_mins = int(self.chunk_size_var.get().split()[0])
        language = self.lang_var.get()
        do_preprocess = self.preprocess_var.get()

        # Capture the settings on the UI thread; worker-thread autosaves reuse this
        # instead of reading widgets from another thread.
        self._session_settings_snapshot = {
            "engine": self.engine_var.get(),
            "language": language,
            "chunk_minutes": chunk_mins,
            "preprocess": bool(do_preprocess)
        }
        self._step_states = {"step1": "pending", "step2": "pending", "step3": "pending", "step4": "pending"}
        self._progress_value = 0.0

        self.worker_thread = threading.Thread(
            target=self._run_pipeline_worker,
            args=(self.selected_audio_file, api_key, chunk_mins, language, do_preprocess),
            daemon=True
        )
        self.worker_thread.start()

    def _cancel_processing(self):
        if messagebox.askyesno(self._t("msg.cancel_title"), self._t("msg.cancel_confirm")):
            self.cancel_event.set()
            self._set_status(self._t("status.cancelling"))

    def _open_or_focus_chunk_monitor(self):
        """Bring chunk monitor dialog to front or recreate it if closed."""
        if self.monitor_dialog and self.monitor_dialog.winfo_exists():
            self.monitor_dialog.deiconify()
            self.monitor_dialog.lift()
            self.monitor_dialog.focus_force()
        elif self.active_chunks_meta:
            self._create_or_show_monitor(self.active_chunks_meta)

    def _create_or_show_monitor(self, chunks_meta: List[Dict]):
        if self.monitor_dialog and self.monitor_dialog.winfo_exists():
            self.monitor_dialog.destroy()

        self.monitor_dialog = ChunkMonitorDialog(
            master=self,
            chunks_meta=chunks_meta,
            on_cancel_callback=self._cancel_processing,
            on_reprocess_callback=self._reprocess_single_chunk,
            on_extract_callback=self._extract_transcript_from_monitor,
            t=self._t,
        )
        self.monitor_btn.configure(state="normal")
        # Sync existing status into monitor
        completed_count = 0
        has_errors = False
        for c in chunks_meta:
            idx = c["chunk_index"]
            st = self.active_chunk_status.get(idx, {"status": "pending"})
            if st["status"] == "done":
                completed_count += 1
            elif st["status"] == "error":
                has_errors = True
            self.monitor_dialog.update_chunk_state(idx, st["status"], st.get("error", ""))
        self.monitor_dialog.update_overall_summary(completed_count, len(chunks_meta), has_errors)

    def _run_pipeline_worker(
        self,
        audio_path: str,
        api_key: str,
        chunk_minutes: int,
        language: str,
        do_preprocess: bool
    ):
        try:
            client = get_gemini_client(api_key) if api_key else None
            file_hash = compute_file_hash(audio_path)
            checkpoint_file = CACHE_DIR / f"progress_cloud_{file_hash}.json"
            model_override = self._get_selected_model_override()

            # Store active pipeline context for single-chunk reprocessing
            self.active_client = client
            self.active_checkpoint_file = checkpoint_file
            self.active_file_hash = file_hash
            self.active_model_override = model_override

            # Step 1: Pre-process Audio
            self._update_step_badge("step1", "working")
            target_audio = audio_path
            if do_preprocess:
                self._set_status(self._t("status.step1_start"))
                target_audio = preprocess_audio(
                    audio_path,
                    progress_callback=lambda msg: self._set_status(
                        f"{self._t('status.step_prefix', n=1)} {msg}"
                    )
                )
                self._update_step_badge("step1", "done")
            else:
                self._set_status(self._t("status.step1_done"))
                self._update_step_badge("step1", "done", self._t("step.skipped"))

            if self.cancel_event.is_set():
                self._on_pipeline_cancelled()
                return

            # Step 2: Slicing into Chunks
            self._update_step_badge("step2", "working")
            self._set_status(self._t("status.step2_start"))
            chunks = split_audio_into_chunks(
                target_audio,
                chunk_minutes=chunk_minutes,
                progress_callback=lambda msg, pct: self._set_progress(
                    pct * 0.2, f"{self._t('status.step_prefix', n=2)} {msg}"
                )
            )
            total_chunks = len(chunks)
            self.active_chunks_meta = chunks
            self._update_step_badge(
                "step2", "done", self._t("step.chunk_count", count=total_chunks)
            )

            # Initialize chunk statuses
            completed_transcripts = {}
            if checkpoint_file.exists():
                try:
                    with open(checkpoint_file, "r", encoding="utf-8") as f:
                        saved_data = json.load(f)
                        completed_transcripts = saved_data.get("chunks", {})
                except Exception:
                    completed_transcripts = {}

            self.active_chunk_status = {}
            for c in chunks:
                idx = c["chunk_index"]
                idx_str = str(idx)
                if idx_str in completed_transcripts and completed_transcripts[idx_str].strip():
                    self.active_chunk_status[idx] = {
                        "status": "done",
                        "text": completed_transcripts[idx_str],
                        "error": ""
                    }
                else:
                    self.active_chunk_status[idx] = {
                        "status": "pending",
                        "text": "",
                        "error": ""
                    }

            # Launch/Update the Floating Monitor Dialog
            self.after(0, lambda: self._create_or_show_monitor(chunks))

            # Step 3: Process Chunks
            self._update_step_badge("step3", "working", f"(0/{total_chunks})")
            previous_tail_context = ""
            completed_count = sum(1 for st in self.active_chunk_status.values() if st["status"] == "done")
            has_errors = False

            # Live preview of already cached text
            self._refresh_live_transcript_view()

            for i, chunk_info in enumerate(chunks):
                if self.cancel_event.is_set():
                    self._on_pipeline_cancelled()
                    return

                idx = chunk_info["chunk_index"]
                idx_str = str(idx)
                chunk_display = f"Chunk {i+1} of {total_chunks}"
                base_pct = 0.2 + (0.6 * (i / total_chunks))

                # If already done from checkpoint, skip network call
                if self.active_chunk_status[idx]["status"] == "done":
                    chunk_text = self.active_chunk_status[idx]["text"]
                    lines = [l for l in chunk_text.splitlines() if l.strip()]
                    previous_tail_context = "\n".join(lines[-4:]) if lines else ""
                    self._set_progress(
                        base_pct, self._t("status.step3_cached", chunks=chunk_display)
                    )
                    continue

                # Mark chunk as working in monitor & main status
                self._update_chunk_monitor_item(idx, "working")
                engine_display_name = model_override or "Gemini Auto-Failover"
                self._set_progress(
                    base_pct,
                    self._t("status.step3_transcribing",
                            chunks=chunk_display, engine=engine_display_name)
                )
                self._update_step_badge("step3", "working", f"({i+1}/{total_chunks})")

                try:
                    if not client:
                        raise ValueError("Gemini API Client is required.")
                    raw_chunk_text = transcribe_audio_chunk(
                        client=client,
                        chunk_file_path=chunk_info["file_path"],
                        previous_tail_transcript=previous_tail_context,
                        progress_callback=lambda msg: self._set_status(
                            self._t("status.step_chunk", chunk=chunk_display, msg=msg)
                        ),
                        model_override=model_override
                    )

                    adjusted_text = adjust_chunk_timestamps(
                        raw_chunk_text,
                        offset_seconds=chunk_info["offset_seconds"]
                    )

                    # Deduplicate with preceding completed chunk text
                    preceding_text = ""
                    for p_i in range(i - 1, -1, -1):
                        p_idx = chunks[p_i]["chunk_index"]
                        if self.active_chunk_status.get(p_idx, {}).get("text"):
                            preceding_text = self.active_chunk_status[p_idx]["text"]
                            break

                    chunk_text = deduplicate_overlap(preceding_text, adjusted_text) if preceding_text else adjusted_text

                    # Save to memory and disk cache
                    self.active_chunk_status[idx] = {
                        "status": "done",
                        "text": chunk_text,
                        "error": ""
                    }
                    completed_transcripts[idx_str] = chunk_text
                    self._save_checkpoint_file(checkpoint_file, file_hash, completed_transcripts)

                    completed_count += 1
                    lines = [l for l in chunk_text.splitlines() if l.strip()]
                    previous_tail_context = "\n".join(lines[-4:]) if lines else ""

                    self._update_chunk_monitor_item(idx, "done")
                    self._refresh_live_transcript_view()

                except Exception as chunk_err:
                    err_msg = str(chunk_err)
                    log.error("Failed chunk %s: %s", chunk_display, err_msg)
                    has_errors = True
                    self.active_chunk_status[idx] = {
                        "status": "error",
                        "text": "",
                        "error": err_msg
                    }
                    self._update_chunk_monitor_item(idx, "error", err_msg)

                # Update monitor overall summary
                self.after(0, lambda c=completed_count, t=total_chunks, e=has_errors: (
                    self.monitor_dialog.update_overall_summary(c, t, e) if self.monitor_dialog and self.monitor_dialog.winfo_exists() else None
                ))

            self.is_processing = False
            self.after(0, lambda: self.start_btn.configure(state="normal"))
            self.after(0, lambda: self.cancel_btn.configure(state="disabled"))

            if completed_count == total_chunks:
                self._update_step_badge("step3", "done", f"({total_chunks}/{total_chunks})")
                self._set_progress(0.80, self._t("status.all_chunks_done"))
            else:
                self._update_step_badge(
                    "step3", "error",
                    f"({self._t('status.chunks_done_suffix', done=completed_count, total=total_chunks)})"
                )
                self._set_progress(
                    0.80, self._t("status.batch_finished", done=completed_count, total=total_chunks)
                )

            # Autosave so settings + partial progress survive a restart
            # even when the user never clicks "Extract Transcript".
            if file_hash:
                self._save_full_session(file_hash)

        except Exception as e:
            tb = traceback.format_exc()
            log.error("Pipeline error:\n%s", tb)
            self.after(0, lambda err=str(e): self._on_pipeline_error(err))

    def _update_chunk_monitor_item(self, chunk_index: int, state: str, detail: str = ""):
        if self.monitor_dialog and self.monitor_dialog.winfo_exists():
            self.after(0, lambda: self.monitor_dialog.update_chunk_state(chunk_index, state, detail))

    def _refresh_live_transcript_view(self):
        """Assembles all currently completed chunks in chronological order and renders in main tab."""
        texts = []
        for c in self.active_chunks_meta:
            idx = c["chunk_index"]
            c_text = self.active_chunk_status.get(idx, {}).get("text", "")
            if c_text.strip():
                texts.append(c_text)
        if texts:
            full_live = "\n\n".join(texts)
            self.after(0, lambda t=full_live: self._update_transcript_view(t))

    def _reprocess_single_chunk(self, chunk_index: int):
        """Reprocess an individual failed or pending chunk in an isolated background thread."""
        chunk_info = next((c for c in self.active_chunks_meta if c["chunk_index"] == chunk_index), None)
        if not chunk_info:
            messagebox.showerror(
                self._t("msg.error"), self._t("msg.chunk_meta_missing", index=chunk_index)
            )
            return

        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showerror(self._t("msg.error"), self._t("msg.key_required"))
            return

        self._update_chunk_monitor_item(chunk_index, "working")
        self._set_status(self._t("status.reprocessing_chunk", index=chunk_index + 1))

        def worker():
            try:
                client = self.active_client or get_gemini_client(api_key)

                # Find preceding tail context
                preceding_text = ""
                for prev_idx in range(chunk_index - 1, -1, -1):
                    if self.active_chunk_status.get(prev_idx, {}).get("text"):
                        preceding_text = self.active_chunk_status[prev_idx]["text"]
                        break

                lines = [l for l in preceding_text.splitlines() if l.strip()]
                tail_context = "\n".join(lines[-4:]) if lines else ""

                raw_text = transcribe_audio_chunk(
                    client=client,
                    chunk_file_path=chunk_info["file_path"],
                    previous_tail_transcript=tail_context,
                    model_override=getattr(self, "active_model_override", None)
                )

                adjusted_text = adjust_chunk_timestamps(raw_text, offset_seconds=chunk_info["offset_seconds"])
                final_text = deduplicate_overlap(preceding_text, adjusted_text) if preceding_text else adjusted_text

                # Update status
                self.active_chunk_status[chunk_index] = {
                    "status": "done",
                    "text": final_text,
                    "error": ""
                }

                # Save checkpoint
                if self.active_checkpoint_file:
                    try:
                        saved = {}
                        if self.active_checkpoint_file.exists():
                            with open(self.active_checkpoint_file, "r", encoding="utf-8") as f:
                                saved = json.load(f).get("chunks", {})
                        saved[str(chunk_index)] = final_text
                        self._save_checkpoint_file(
                            self.active_checkpoint_file,
                            self.active_file_hash,
                            saved
                        )
                    except Exception as ce:
                        log.warning("Failed saving checkpoint during reprocess: %s", ce)

                self._update_chunk_monitor_item(chunk_index, "done")
                self._refresh_live_transcript_view()

                # Recompute overall count
                total = len(self.active_chunks_meta)
                completed = sum(1 for st in self.active_chunk_status.values() if st["status"] == "done")
                has_err = any(st["status"] == "error" for st in self.active_chunk_status.values())
                self.after(0, lambda c=completed, t=total, e=has_err: (
                    self.monitor_dialog.update_overall_summary(c, t, e) if self.monitor_dialog and self.monitor_dialog.winfo_exists() else None
                ))
                self._set_status(self._t("status.reprocess_done", index=chunk_index + 1))
                if self.active_file_hash:
                    self._save_full_session(self.active_file_hash)

            except Exception as e:
                err_str = str(e)
                log.error("Reprocess of chunk %d failed: %s", chunk_index, err_str)
                self.active_chunk_status[chunk_index] = {
                    "status": "error",
                    "text": "",
                    "error": err_str
                }
                self._update_chunk_monitor_item(chunk_index, "error", err_str)
                self._set_status(
                    self._t("status.reprocess_failed", index=chunk_index + 1, error=err_str[:40])
                )

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _extract_transcript_from_monitor(self):
        """Combines all green chunk transcripts in proper sequence and populates the main app."""
        total = len(self.active_chunks_meta)
        missing = [c["chunk_index"] for c in self.active_chunks_meta if self.active_chunk_status.get(c["chunk_index"], {}).get("status") != "done"]

        if missing:
            msg = self._t("msg.partial_chunks", indexes=[m + 1 for m in missing])
            if not messagebox.askyesno(self._t("msg.partial_extraction"), msg):
                return

        # Combine transcripts in strict sequential order
        ordered_parts = []
        for c in sorted(self.active_chunks_meta, key=lambda x: x["chunk_index"]):
            idx = c["chunk_index"]
            c_text = self.active_chunk_status.get(idx, {}).get("text", "")
            if c_text.strip():
                ordered_parts.append(c_text)

        full_transcript = "\n\n".join(ordered_parts)
        self.raw_transcript = full_transcript
        self.processed_transcript = full_transcript
        self.detected_speakers = extract_speakers(full_transcript)

        self._update_transcript_view(full_transcript)
        self._update_step_badge("step3", "done", f"({len(ordered_parts)}/{total})")
        self.gen_minutes_btn.configure(state="normal")

        # Save meeting session so it restores across app restarts
        if self.active_file_hash:
            self._save_full_session(self.active_file_hash)

        # Minimize / close monitor
        if self.monitor_dialog and self.monitor_dialog.winfo_exists():
            self.monitor_dialog.withdraw()

        self._set_progress(1.0, self._t("status.extracted", count=len(ordered_parts)))
        messagebox.showinfo(
            self._t("msg.extraction_complete"),
            self._t("msg.extracted_body", count=len(ordered_parts))
        )

    def _save_checkpoint_file(self, checkpoint_path, file_hash, chunks_dict):
        try:
            with open(checkpoint_path, "w", encoding="utf-8") as f:
                json.dump({
                    "audio_hash": file_hash,
                    "engine": "cloud",
                    "chunks": chunks_dict,
                    "updated_at": datetime.now().isoformat()
                }, f, indent=2)
        except Exception as e:
            log.warning("Could not write checkpoint file: %s", e)

    def _execute_minutes_synthesis(self, client, language: str, file_hash: str):
        """
        Isolated minutes synthesis execution.
        Safeguards transcript so a minutes failure never marks the transcript as failed or crashes the session.
        """
        self._update_step_badge("step4", "working")
        self._set_progress(
            0.85,
            self._t("status.step4_start",
                    language=display_minutes_lang(language, self.ui_locale))
        )

        try:
            if not client:
                api_key = self.api_key_var.get().strip()
                if not api_key:
                    raise ValueError(self._t("msg.key_required"))
                client = get_gemini_client(api_key)

            transcript_to_use = self.processed_transcript or self.raw_transcript
            if not transcript_to_use.strip():
                raise ValueError("Transcript is empty. Cannot generate minutes.")

            self.generated_minutes = generate_meeting_minutes(
                client=client,
                full_transcript=transcript_to_use,
                language=language,
                progress_callback=lambda msg: self._set_status(
                    f"{self._t('status.step_prefix', n=4)} {msg}"
                ),
                model_override=self._get_selected_model_override()
            )

            sections = parse_minutes_sections(self.generated_minutes)
            self.after(0, lambda secs=sections: self._populate_minutes_tabs(secs))
            self.after(0, self._hide_minutes_error_banner)
            self._update_step_badge("step4", "done")
            self._save_full_session(file_hash)
            self._set_progress(1.0, self._t("status.all_complete"))
            self.after(0, self._on_pipeline_finished)

        except Exception as err:
            err_msg = str(err)
            log.warning("Minutes synthesis failed (transcript remains protected): %s", err_msg)
            self._update_step_badge("step4", "error", self._t("step.failed"))
            self.after(0, lambda msg=err_msg: self._show_minutes_error_banner(msg))
            self._set_progress(0.80, self._t("status.minutes_failed"))
            self.is_processing = False
            self.after(0, lambda: self.start_btn.configure(state="normal"))
            self.after(0, lambda: self.cancel_btn.configure(state="disabled"))
            self.after(0, lambda: self.gen_minutes_btn.configure(state="normal"))

    def _start_minutes_generation_only(self):
        """
        Independent Step 4 trigger.
        Enables user to generate or retry minutes from existing transcript without re-transcribing.
        """
        transcript_to_use = self.processed_transcript or self.raw_transcript
        if not transcript_to_use.strip():
            messagebox.showwarning(self._t("msg.notice"), self._t("msg.no_transcript"))
            return

        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showerror(self._t("msg.error"), self._t("msg.key_required_minutes"))
            return

        if self.is_processing:
            messagebox.showinfo(self._t("msg.busy"), self._t("msg.task_running"))
            return

        self.is_processing = True
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="disabled")
        self.gen_minutes_btn.configure(state="disabled")
        self._hide_minutes_error_banner()

        language = self.lang_var.get()
        file_hash = compute_file_hash(self.selected_audio_file) if self.selected_audio_file else "manual_session"

        def runner():
            try:
                client = get_gemini_client(api_key)
                self._execute_minutes_synthesis(client, language, file_hash)
            except Exception as e:
                err_msg = str(e)
                log.error("Manual minutes generation failed: %s", err_msg)
                self._update_step_badge("step4", "error", "(Failed)")
                self.after(0, lambda msg=err_msg: self._show_minutes_error_banner(msg))
                self.is_processing = False
                self.after(0, lambda: self.start_btn.configure(state="normal"))
                self.after(0, lambda: self.gen_minutes_btn.configure(state="normal"))

        t = threading.Thread(target=runner, daemon=True)
        t.start()

    def _update_step_badge(self, step_key: str, state: str, extra: str = ""):
        """
        Update the visual state of a step badge.
        state: 'pending' (gray), 'working' (blue), 'done' (green), 'error' (red)
        """
        badge = self.step_badges.get(step_key)
        if not badge:
            return

        colors = {
            "pending": ("gray", ("#E0E0E0", "#2B2B2B"), "⚪"),
            "working": ("#1976D2", ("#BBDEFB", "#0D47A1"), "🔵"),
            "done": ("#2E7D32", ("#C8E6C9", "#1B5E20"), "🟢"),
            "error": ("#C62828", ("#FFCDD2", "#B71C1C"), "🔴")
        }
        fg_text, bg_col, icon = colors.get(state, colors["pending"])
        if step_key in self._step_states:
            self._step_states[step_key] = state
        # Read the base label from _step_labels rather than re-parsing the badge's
        # rendered text: split()[0] would discard the label word entirely.
        base_name = self._step_labels.get(step_key, "")
        label_text = f"{base_name} {extra}".strip() if extra else base_name
        self.after(0, lambda: badge.configure(
            text=f"{label_text} {icon}",
            text_color=fg_text,
            fg_color=bg_col
        ))

    def _reset_all_step_badges(self):
        for k in ["step1", "step2", "step3", "step4"]:
            self._update_step_badge(k, "pending")

    def _get_current_settings(self) -> Dict:
        """Snapshot the settings widgets so they can be restored with the session."""
        # Autosaves also fire from the worker thread, where touching Tk widgets is
        # unsafe. During a run the snapshot taken on the UI thread is used instead.
        if self.is_processing and self._session_settings_snapshot:
            return dict(self._session_settings_snapshot)
        try:
            chunk_mins = int(str(self.chunk_size_var.get()).split()[0])
        except (ValueError, IndexError):
            chunk_mins = DEFAULT_CHUNK_MINUTES
        return {
            "engine": self.engine_var.get(),
            "language": self.lang_var.get(),
            "chunk_minutes": chunk_mins,
            "preprocess": bool(self.preprocess_var.get())
        }

    def _get_current_status(self) -> Dict:
        """Snapshot step badge states, per-chunk status and progress for the session file."""
        chunks = []
        for idx, st in sorted(self.active_chunk_status.items()):
            chunks.append({
                "index": idx,
                "status": st.get("status", "pending"),
                "error": st.get("error", "")
            })

        return {
            "steps": dict(self._step_states),
            "chunks": chunks,
            "progress": self._progress_value
        }

    def _save_full_session(self, audio_hash: str) -> bool:
        """Persist settings, status and output so the workspace reloads on file select."""
        if not audio_hash:
            return False

        payload = build_session_payload(
            audio_hash=audio_hash,
            audio_path=self.selected_audio_file,
            settings=self._get_current_settings(),
            status=self._get_current_status(),
            raw_transcript=self.raw_transcript,
            processed_transcript=self.processed_transcript,
            generated_minutes=self.generated_minutes,
            detected_speakers=self.detected_speakers,
            speaker_mapping=self.speaker_mapping
        )

        session_file = session_path(CACHE_DIR, audio_hash)
        if save_session(payload, session_file):
            self.active_file_hash = audio_hash
            self._set_save_session_enabled(True)
            log.info("Saved full meeting session to %s", session_file)
            return True

        log.warning("Failed to save meeting session: %s", session_file)
        return False

    def _set_save_session_enabled(self, enabled: bool):
        """Toggle the Save Session button; safe to call from the worker thread."""
        def apply():
            if hasattr(self, "save_session_btn"):
                self.save_session_btn.configure(state="normal" if enabled else "disabled")
        try:
            self.after(0, apply)
        except Exception:
            apply()

    def _save_session_manually(self):
        """Explicit user-triggered save from the 💾 Save Session button."""
        if not self.selected_audio_file or not os.path.exists(self.selected_audio_file):
            messagebox.showwarning(self._t("msg.save_session"), self._t("msg.save_no_file"))
            return

        if self.is_processing:
            if not messagebox.askyesno(
                self._t("msg.save_session"),
                self._t("msg.save_while_running")
            ):
                return

        audio_hash = compute_file_hash(self.selected_audio_file)
        if self._save_full_session(audio_hash):
            messagebox.showinfo(
                self._t("msg.session_saved"),
                self._t("msg.session_saved_body", name=Path(self.selected_audio_file).name)
            )
        else:
            messagebox.showerror(self._t("msg.save_session"), self._t("msg.session_save_failed"))

    def _on_app_close(self):
        """Autosave the active session when the window is closed."""
        if self.is_processing and self.active_file_hash:
            self._save_full_session(self.active_file_hash)
        try:
            self.destroy()
        except Exception:
            pass

    def _load_full_session_if_exists(self, audio_path: str) -> bool:
        """Restore settings, status and output from a saved session for this audio file."""
        try:
            audio_hash = compute_file_hash(audio_path)
            data = load_session(session_path(CACHE_DIR, audio_hash))
            if data is None:
                return False

            self.raw_transcript = data["raw_transcript"]
            self.processed_transcript = data["processed_transcript"] or self.raw_transcript
            self.generated_minutes = data["generated_minutes"]
            self.detected_speakers = data["detected_speakers"]
            self.speaker_mapping = data["speaker_mapping"]
            self.active_file_hash = audio_hash
            self._set_save_session_enabled(True)

            self._apply_saved_settings(data["settings"])
            self._apply_saved_status(data["status"])

            if self.processed_transcript:
                self._update_transcript_view(self.processed_transcript)
                if not self.generated_minutes:
                    self.gen_minutes_btn.configure(state="normal")

            if self.generated_minutes:
                sections = parse_minutes_sections(self.generated_minutes)
                self._populate_minutes_tabs(sections)
                self._hide_minutes_error_banner()

            chunk_summary = self._describe_restored_chunks(data["status"])
            if chunk_summary:
                message = self._t(
                    "status.session_restored",
                    name=Path(audio_path).name, chunks=chunk_summary
                )
            else:
                message = self._t("status.session_restored_plain")
            self._set_progress(data["status"]["progress"], message)
            return True
        except Exception as e:
            log.warning("Failed to restore session: %s", e)
            return False

    def _apply_saved_settings(self, settings: Dict):
        """Push stored settings onto the widgets, ignoring anything no longer valid."""
        clean = normalize_settings(settings)

        # set() does not fire the option menu command callback, so this will not
        # reset the chunk dropdown values or emit a misleading status message.
        self.engine_var.set(clean["engine"])
        self.chunk_size_var.set(f"{clean['chunk_minutes']} min")
        self.preprocess_var.set(clean["preprocess"])
        self._session_settings_snapshot = dict(clean)

        # The UI locale governs the minutes language. A session records the
        # language that produced its output, but that no longer overrides the
        # current preference, so re-cascade after the stored value is applied.
        self._cascade_minutes_lang()
        self._refresh_output_lang_chip()
        clean["language"] = self.lang_var.get()
        self._session_settings_snapshot = dict(clean)

    def _apply_saved_status(self, status: Dict):
        """Restore step badges, per-chunk statuses and progress from the session file."""
        for key, state in status["steps"].items():
            self._update_step_badge(key, state)

        restored_chunks = {}
        for entry in status["chunks"]:
            restored_chunks[entry["index"]] = {
                "status": entry["status"],
                "text": "",
                "error": entry["error"]
            }
        if restored_chunks:
            self.active_chunk_status.update(restored_chunks)

        self.progress_bar.set(status["progress"])
        self._progress_value = status["progress"]
        if status["steps"].get("step3") == "done":
            self.gen_minutes_btn.configure(state="normal")

    def _describe_restored_chunks(self, status: Dict) -> str:
        """Summarise restored chunk counts for the status line."""
        chunks = status.get("chunks") or []
        if not chunks:
            return ""
        done = sum(1 for c in chunks if c["status"] == "done")
        return self._t("status.chunks_done_suffix", done=done, total=len(chunks))

    def _reset_workspace(self):
        """
        Unconditionally clears all transcripts, minutes, monitors, and purges all
        cached progress, chunks, manifests, and session checkpoints so the next run is 100% fresh.
        """
        if self.is_processing:
            messagebox.showwarning(self._t("msg.notice"), self._t("msg.reset_running"))
            return

        # Clear text in all 4 tabs
        for tb in [self.txt_transcript, self.txt_minutes, self.txt_summary, self.txt_actions]:
            tb.delete("1.0", "end")

        # Clear memory state
        self.raw_transcript = ""
        self.processed_transcript = ""
        self.generated_minutes = ""
        self.detected_speakers = []
        self.speaker_mapping = {}
        self.active_chunks_meta = []
        self.active_chunk_status = {}

        # Reset badges & progress
        self._reset_all_step_badges()
        self.progress_bar.set(0.0)
        self._progress_value = 0.0
        self._session_settings_snapshot = None
        self._hide_minutes_error_banner()
        self.gen_minutes_btn.configure(state="disabled")
        self.monitor_btn.configure(state="disabled")
        self.active_file_hash = ""
        self._set_save_session_enabled(True)

        # Close floating monitor dialog if open
        if self.monitor_dialog and self.monitor_dialog.winfo_exists():
            self.monitor_dialog.destroy()
            self.monitor_dialog = None

        # Cleanly purge all cache files across .sttmeet_cache and .sttmeet_cache/chunks
        purged_count = 0
        try:
            for item in CACHE_DIR.glob("*"):
                if item.is_file():
                    try:
                        item.unlink()
                        purged_count += 1
                    except Exception:
                        pass
            if CHUNKS_DIR.exists():
                for item in CHUNKS_DIR.glob("*"):
                    if item.is_file():
                        try:
                            item.unlink()
                            purged_count += 1
                        except Exception:
                            pass
            log.info("Reset complete: purged %d cache files.", purged_count)
        except Exception as e:
            log.warning("Could not clear cache files: %s", e)

        self._set_status(self._t("status.workspace_reset"))

    def _show_minutes_error_banner(self, err_msg: str):
        self.minutes_banner_label.configure(
            text=self._t("minutes.banner_error", error=err_msg[:60])
        )
        self.minutes_banner_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 2))

    def _hide_minutes_error_banner(self):
        self.minutes_banner_frame.grid_forget()

    def _set_status(self, message: str):
        self.after(0, lambda: self.status_label.configure(text=message))

    def _set_progress(self, pct: float, message: str):
        self._progress_value = max(0.0, min(float(pct), 1.0))
        self.after(0, lambda: (
            self.progress_bar.set(pct),
            self.status_label.configure(text=message)
        ))

    def _update_transcript_view(self, text: str):
        self.txt_transcript.delete("1.0", "end")
        self.txt_transcript.insert("1.0", text)

    def _populate_minutes_tabs(self, sections: Dict[str, str]):
        self.txt_minutes.delete("1.0", "end")
        self.txt_minutes.insert("1.0", sections.get("full_text", ""))

        self.txt_summary.delete("1.0", "end")
        self.txt_summary.insert("1.0", sections.get("summary", self._t("content.summary_missing")))

        self.txt_actions.delete("1.0", "end")
        self.txt_actions.insert("1.0", sections.get("action_items", self._t("content.actions_missing")))

    def _on_pipeline_finished(self):
        self.is_processing = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        messagebox.showinfo(
            self._t("msg.completed"),
            self._t("msg.completed_body")
        )

    def _on_pipeline_cancelled(self):
        self.is_processing = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self._set_status(self._t("status.cancelled"))
        if self.active_file_hash:
            self._save_full_session(self.active_file_hash)

    def _on_pipeline_error(self, error_message: str):
        self.is_processing = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self._set_status(self._t("status.error", error=error_message))
        messagebox.showerror(
            self._t("msg.transcription_error"),
            self._t("msg.transcription_error_body", error=error_message)
        )

    # -------------------------------------------------------------
    # Speaker Mapping Dialog
    # -------------------------------------------------------------
    def _open_speaker_mapping_dialog(self):
        if not self.raw_transcript:
            messagebox.showinfo(self._t("msg.speaker_mapping"), self._t("msg.no_speakers_yet"))
            return

        speakers = self.detected_speakers or extract_speakers(self.raw_transcript)
        if not speakers:
            messagebox.showinfo(self._t("msg.speaker_mapping"), self._t("msg.no_speakers"))
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title(self._t("speakers.title"))
        dialog.geometry("450x380")
        dialog.transient(self)
        dialog.grab_set()

        lbl = ctk.CTkLabel(
            dialog,
            text=self._t("speakers.assign"),
            font=ctk.CTkFont(weight="bold")
        )
        lbl.pack(padx=16, pady=(16, 10), anchor="w")

        scroll_frame = ctk.CTkScrollableFrame(dialog, height=220)
        scroll_frame.pack(padx=16, pady=6, fill="both", expand=True)

        entry_map = {}
        for spk in speakers:
            row_frame = ctk.CTkFrame(scroll_frame, fg_color="transparent")
            row_frame.pack(fill="x", pady=4)

            spk_lbl = ctk.CTkLabel(row_frame, text=f"{spk}:", width=90, anchor="w")
            spk_lbl.pack(side="left", padx=4)

            name_entry = ctk.CTkEntry(row_frame, placeholder_text=self._t("speakers.placeholder"))
            name_entry.pack(side="left", fill="x", expand=True, padx=4)
            saved_name = self.speaker_mapping.get(spk, "")
            if saved_name:
                name_entry.insert(0, saved_name)
            entry_map[spk] = name_entry

        def apply_mapping():
            mapping = {spk: entry.get().strip() for spk, entry in entry_map.items() if entry.get().strip()}
            if not mapping:
                dialog.destroy()
                return

            self.speaker_mapping = dict(mapping)
            self.processed_transcript = apply_speaker_mapping(self.raw_transcript, mapping)
            self._update_transcript_view(self.processed_transcript)

            if self.generated_minutes:
                self.generated_minutes = apply_speaker_mapping(self.generated_minutes, mapping)
                sections = parse_minutes_sections(self.generated_minutes)
                self._populate_minutes_tabs(sections)

            if self.active_file_hash:
                self._save_full_session(self.active_file_hash)

            dialog.destroy()
            messagebox.showinfo(self._t("msg.applied"), self._t("msg.speakers_applied"))

        apply_btn = ctk.CTkButton(dialog, text=self._t("speakers.apply"), command=apply_mapping)
        apply_btn.pack(padx=16, pady=12)

    # -------------------------------------------------------------
    # Document Export Handler
    # -------------------------------------------------------------
    def _export_document(self, fmt: str):
        if not self.processed_transcript and not self.generated_minutes:
            messagebox.showwarning(self._t("msg.export"), self._t("msg.export_nothing"))
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = Path(self.selected_audio_file).stem if self.selected_audio_file else "Meeting"

        # Export title and filenames stay as-is: they are document content, not UI
        # chrome, and the exported documents remain bilingual by design.
        title = f"Minit Mesyuarat - {base_name}"
        minutes_content = self.generated_minutes or self.processed_transcript
        transcript_content = self.processed_transcript

        if fmt in ["docx", "all"]:
            save_path = filedialog.asksaveasfilename(
                title=self._t("filepicker.save_docx"),
                initialfile=f"Minit_{base_name}_{timestamp}.docx",
                defaultextension=".docx",
                filetypes=[(self._t("filepicker.word_doc"), "*.docx")]
            )
            if save_path:
                export_to_docx(
                    file_path=save_path,
                    title=title,
                    minutes_text=minutes_content,
                    raw_transcript=transcript_content
                )

        if fmt in ["md", "all"]:
            save_path = filedialog.asksaveasfilename(
                title=self._t("filepicker.save_md"),
                initialfile=f"Minit_{base_name}_{timestamp}.md",
                defaultextension=".md",
                filetypes=[(self._t("filepicker.markdown_doc"), "*.md")]
            )
            if save_path:
                export_to_markdown(
                    file_path=save_path,
                    title=title,
                    minutes_text=minutes_content,
                    transcript=transcript_content
                )

        if fmt in ["txt", "all"]:
            save_path = filedialog.asksaveasfilename(
                title=self._t("filepicker.save_txt"),
                initialfile=f"Minit_{base_name}_{timestamp}.txt",
                defaultextension=".txt",
                filetypes=[(self._t("filepicker.text_file"), "*.txt")]
            )
            if save_path:
                export_to_text(
                    file_path=save_path,
                    title=title,
                    minutes_text=minutes_content,
                    transcript=transcript_content
                )

        messagebox.showinfo(self._t("msg.export_success"), self._t("msg.export_done"))

def run_app():
    app = STTMeetApp()
    app.mainloop()
