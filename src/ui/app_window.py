"""
STTMeet GUI Application Window
Modern Desktop UI built with CustomTkinter.
Features:
- Slide-in hamburger menu: Settings (API Key), Save Session, Log folder, About
- Settings modal: API Key configuration & verification, FFmpeg check
- Audio File Picker with duration, size, and token estimation
- Language Selection (Bahasa Melayu, English)
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
import webbrowser
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
    MINUTES_MODEL_NAME,
    API_KEY_URL
)
from ..logger import LOG_FILE, get_logger
from ..i18n import (
    ALL_MODES,
    DEFAULT_LOCALE,
    MINUTES_LANG_BY_UI_LOCALE,
    display_minutes_lang,
    display_template_name,
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
from ..cancellation import CancelledError
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
    generate_action_items,
    parse_minutes_sections
)
from ..recap_generator import generate_meeting_recap
from .markdown_view import MarkdownViewer
from .docs_viewer import DocsWindow
from .tooltip import Tooltip
from ..exporter import (
    DocxUnavailableError,
    export_to_docx,
    export_to_markdown,
    export_to_text
)
from ..session_store import (
    DEFAULT_SETTINGS,
    VALID_CHUNK_MINUTES,
    VALID_ENGINES,
    VALID_LANGUAGES,
    VALID_TEMPLATES,
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
# are therefore always set explicitly as (light, dark) tuples; see theme.py.
from .theme import (
    ACCENT_FG,
    ACCENT_HOVER,
    ACCENT_TEXT,
    MUTED_TEXT,
    ON_ACCENT_TEXT,
    STATUS_BAR_BG,
    STATUS_BAR_BORDER,
    TOOLBAR_BG,
    TOOLBAR_BORDER,
    TRANSPARENT_HOVER,
    TRANSPARENT_TEXT,
    center_window,
)

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

    While the pipeline is transcribing, closing is blocked (see set_close_locked) so
    the live view cannot be dismissed mid-run. This deliberately avoids grab_set: the
    main window and its other modals stay usable while the monitor is locked.
    """
    def __init__(self, master, chunks_meta: List[Dict], on_reprocess_callback, on_extract_callback,
                 on_cancel_callback=None, t: Optional[Callable[..., str]] = None):
        super().__init__(master)
        self.master_app = master
        self.chunks_meta = chunks_meta
        self.on_reprocess_callback = on_reprocess_callback
        self.on_extract_callback = on_extract_callback

        # Translation callable supplied by the main window so this dialog follows
        # language switches. Falls back to English-only if none is given.
        self._t = t or (lambda key, **fmt: translate(key, "en", **fmt))
        self._i18n: List[Tuple[Any, str]] = []
        self._chunk_detail: Dict[int, str] = {}  # chunk index -> last error detail

        self._close_key = "monitor.hide"

        self.title(self._t("monitor.title"))
        center_window(self, master, 640, 520)
        self.minsize(550, 400)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._on_close_requested)

        self.row_widgets: Dict[int, Dict] = {}
        self._build_ui()

    def _label(self, widget, key: str, **fmt):
        self._i18n.append((widget, key))
        widget.configure(text=self._t(key, **fmt))
        return widget

    def set_close_locked(self, locked: bool):
        """No-op retained for backwards compatibility. Window can always be hidden."""
        pass

    def _on_close_requested(self):
        """Close path for X button and Hide button — always hides the floating panel."""
        self.withdraw()

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
        header_frame = ctk.CTkFrame(self, corner_radius=0)
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
        self.scroll_frame = ctk.CTkScrollableFrame(self, corner_radius=0)
        self.scroll_frame.grid(row=1, column=0, padx=14, pady=6, sticky="nsew")
        self.scroll_frame.grid_columnconfigure(1, weight=1)

        for i, chunk in enumerate(self.chunks_meta):
            idx = chunk["chunk_index"]
            start_sec = chunk.get("start_ms", 0) / 1000.0
            end_sec = chunk.get("end_ms", 0) / 1000.0
            time_str = f"{format_duration(start_sec)} - {format_duration(end_sec)}"

            card = ctk.CTkFrame(self.scroll_frame, corner_radius=0, fg_color=("#F5F5F5", "#242424"))
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
                corner_radius=0,
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
        bottom_frame.grid_columnconfigure(0, weight=1)

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
        self.btn_extract.grid(row=0, column=1, padx=6, pady=6, sticky="e")
        self._i18n.append((self.btn_extract, "monitor.extract"))

        self.btn_close = ctk.CTkButton(
            bottom_frame,
            text=self._t(self._close_key),
            width=100,
            command=self._on_close_requested
        )
        self.btn_close.grid(row=0, column=2, padx=(6, 0), pady=6, sticky="e")
        self._i18n.append((self.btn_close, lambda _t: _t(self._close_key)))

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
        elif has_errors:
            status_text += self._t("monitor.summary_errors")
            self.btn_extract.configure(state="disabled")
        else:
            self.btn_extract.configure(state="disabled")

        self.summary_label.configure(text=status_text)


# Traditional icon toolbar: (i18n key, glyph, handler name resolved on the app).
_TOOLBAR_ITEMS = (
    ("toolbar.open", "\U0001F4C2", "_browse_audio_file"),
    ("toolbar.start", "\u25B6", "_start_processing_pipeline"),
    ("toolbar.cancel", "\u23F9", "_cancel_processing"),
    ("toolbar.save", "\U0001F4BE", "_save_session_manually"),
    ("toolbar.docs", "\U0001F4DA", "_open_docs_window"),
    ("toolbar.about", "\u2139\uFE0F", "_open_about_dialog"),
)


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

        # Meeting Minute Template selector (Action Minutes, Discussion, Three-Column, Board Governance)
        saved_template = get_pref("template", "action_minutes")
        if saved_template not in VALID_TEMPLATES:
            saved_template = "action_minutes"
        self.template_var = ctk.StringVar(value=saved_template)

        self.title(self._t("window.title", version=get_display_version()))
        self.geometry("1100x820")
        self.minsize(950, 750)

        # Worker & State
        self.worker_thread: Optional[threading.Thread] = None
        self.cancel_event = threading.Event()
        self.is_processing = False
        # True only while the step-3 chunk loop can still observe cancel_event.
        # Cancel is meaningless during e.g. minutes-only generation.
        self._transcribing = False

        # API Key lives here for the whole session; the entry widget only exists
        # inside the Settings modal. Seeded from .env so a restart restores it.
        self.api_key_var: ctk.StringVar = ctk.StringVar(value=get_api_key())

        self.selected_audio_file: Optional[str] = None
        self.audio_duration_seconds: float = 0.0
        self.raw_transcript: str = ""
        self.processed_transcript: str = ""
        self.generated_minutes: str = ""
        self.generated_recap: str = ""
        self.generated_actions: str = ""
        self.cached_minutes_by_template: Dict[str, str] = {}
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

        # Status bar indicators
        self.menu_key_badge = None
        self._docs_window = None

        self._build_ui()
        self._refresh_output_lang_chip()
        self._refresh_menu_key_badge()
        self._check_initial_environment()
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)
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

        # 0. Menu bar (native tk.Menu)
        self._build_menu_bar()

        # 1. Toolbar (icon buttons + language chip)
        self._build_toolbar()

        # 2. File Selection & Audio Details
        self._build_file_section()

        # 3. Action Controls & Progress
        self._build_controls_section()

        # 4. Center Section: Tabbed Content Viewer
        self._build_tabs_section()

        # 5. Bottom Section: Export Bar
        self._build_bottom_bar()

        # 6. Status Bar
        self._build_status_bar()

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
        display = display_minutes_lang(self.lang_var.get(), self.ui_locale)
        chip_var.set(self._t("control.output_lang", value=display))

    def _open_menu_for_language(self):
        """Cycle to the next language when the output-language chip is clicked."""
        modes = list(ALL_MODES)
        current = modes.index(self.ui_locale) if self.ui_locale in modes else 0
        next_mode = modes[(current + 1) % len(modes)]
        self._set_ui_locale(next_mode)

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
        self._refresh_template_dropdown()
        try:
            self._retranslate_menu_bar()
            self._refresh_docs_window()
            self._refresh_ffmpeg_badge()
            self._refresh_menu_key_badge()
        except Exception:
            log.warning("Could not retranslate menu bar", exc_info=True)
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
            ("tab_recap", "tab.recap"),
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

    def _build_toolbar(self):
        """Traditional icon toolbar. Labels surface on hover via the status bar."""
        toolbar = ctk.CTkFrame(
            self, corner_radius=0, fg_color=TOOLBAR_BG,
            border_width=1, border_color=TOOLBAR_BORDER
        )
        toolbar.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        toolbar.grid_columnconfigure(len(_TOOLBAR_ITEMS), weight=1)

        self._status_hint_previous: Optional[str] = None
        self.tb_buttons: Dict[str, ctk.CTkButton] = {}

        for idx, (key, icon, handler) in enumerate(_TOOLBAR_ITEMS):
            btn = ctk.CTkButton(
                toolbar,
                text=icon,
                width=38,
                height=32,
                corner_radius=0,
                fg_color="transparent",
                text_color=TRANSPARENT_TEXT,
                hover_color=TRANSPARENT_HOVER,
                font=ctk.CTkFont(size=15),
                command=getattr(self, handler)
            )
            btn.grid(row=0, column=idx, padx=1, pady=2, sticky="w")
            btn.bind("<Enter>", lambda _e, k=key: self._show_toolbar_hint(k))
            btn.bind("<Leave>", lambda _e: self._clear_toolbar_hint())
            tip_key = key.replace("toolbar.", "toolbar.tip_")
            Tooltip(btn, lambda tk=tip_key: self._t(tk))
            self.tb_buttons[key] = btn

        # Toolbar twins of the main control buttons must grey out with them.
        # Wired in _build_controls_section, where those buttons now exist.

        locale_frame = ctk.CTkFrame(toolbar, fg_color="transparent", corner_radius=0)
        locale_frame.grid(row=0, column=len(_TOOLBAR_ITEMS) + 1, padx=(10, 4), pady=2, sticky="e")
        for i, mode in enumerate(ALL_MODES):
            btn = ctk.CTkButton(
                locale_frame,
                text=mode_label(mode, self.ui_locale),
                width=44,
                height=26,
                corner_radius=0,
                font=ctk.CTkFont(size=10),
                fg_color=ACCENT_FG if mode == self.ui_locale else "transparent",
                text_color=ACCENT_TEXT if mode == self.ui_locale else TRANSPARENT_TEXT,
                hover_color=ACCENT_HOVER if mode == self.ui_locale else TRANSPARENT_HOVER,
                command=lambda m=mode: self._set_ui_locale(m)
            )
            btn.grid(row=0, column=i, padx=1, pady=1)
            tip_mode_key = f"toolbar.tip_locale_{mode}"
            Tooltip(btn, lambda tmk=tip_mode_key: self._t(tmk))
            self._locale_buttons[mode] = btn
        self._refresh_locale_toggle()

        # Initially disable toolbar.save until an audio file is loaded or session restored
        tb_save = self.tb_buttons.get("toolbar.save")
        if tb_save is not None:
            tb_save.configure(state="disabled")

    def _show_toolbar_hint(self, key: str):
        """Show a toolbar button's localized name in the status bar on hover."""
        if self._status_hint_previous is None:
            self._status_hint_previous = self.status_label.cget("text")
        self._set_status(self._t(key))

    def _clear_toolbar_hint(self):
        """Restore whatever the status bar showed before the hover."""
        if self._status_hint_previous is not None:
            previous, self._status_hint_previous = self._status_hint_previous, None
            self._set_status(previous)

    def _mirror_button_state(self, source_key: str, target_key: str):
        """Keep a toolbar twin enabled/disabled in step with its main button.

        The pipeline toggles state on the control-section buttons from many
        places; mirroring keeps the toolbar honest without touching them.
        """
        source = getattr(self, source_key, None)
        target = self.tb_buttons.get(target_key)
        if source is None or target is None:
            return
        original = source.configure

        def configure(*args, **kwargs):
            result = original(*args, **kwargs)
            state = kwargs.get("state")
            if state is not None:
                try:
                    target.configure(state=state)
                except Exception:
                    log.warning("Could not mirror toolbar button state", exc_info=True)
            return result

        source.configure = configure

        # Adopt the current state; the mirror only propagates later changes.
        try:
            target.configure(state=source.cget("state"))
        except Exception:
            log.warning("Could not sync initial toolbar button state", exc_info=True)

    def _wire_toolbar_state(self):
        """Called once the control-section buttons exist."""
        self._mirror_button_state("start_btn", "toolbar.start")
        self._mirror_button_state("cancel_btn", "toolbar.cancel")

    def _refresh_locale_toggle(self):
        """Highlight the active language button and re-label all of them."""
        for mode, btn in getattr(self, "_locale_buttons", {}).items():
            if not btn.winfo_exists():
                continue
            active = (mode == self.ui_locale)
            btn.configure(
                text=mode_label(mode, self.ui_locale),
                fg_color=("#0078D4", "#005A9E") if active else "transparent",
                text_color=ON_ACCENT_TEXT if active else TRANSPARENT_TEXT,
                hover_color=("#005A9E", "#004578") if active else TRANSPARENT_HOVER,
                font=ctk.CTkFont(size=10, weight="bold" if active else "normal"),
            )

    def _build_menu_bar(self):
        self.menubar = tk.Menu(self, tearoff=0)

        file_menu = tk.Menu(self.menubar, tearoff=0)
        file_menu.add_command(label=self._t("menubar.open_audio"), command=self._browse_audio_file)
        file_menu.add_command(label=self._t("menubar.save_session"), command=self._save_session_manually)
        file_menu.add_command(label=self._t("menubar.reset"), command=self._reset_workspace)
        file_menu.add_separator()
        file_menu.add_command(label=self._t("menubar.exit"), command=self._on_app_close)
        self.menubar.add_cascade(label=self._t("menubar.file"), menu=file_menu)

        edit_menu = tk.Menu(self.menubar, tearoff=0)
        edit_menu.add_command(label=self._t("menubar.map_speakers"), command=self._open_speaker_mapping_dialog)
        self.menubar.add_cascade(label=self._t("menubar.edit"), menu=edit_menu)

        tools_menu = tk.Menu(self.menubar, tearoff=0)
        tools_menu.add_command(label=self._t("menubar.settings"), command=self._open_settings_dialog)
        tools_menu.add_command(label=self._t("menubar.wizard"), command=self._open_audio_setup_wizard_manual)
        tools_menu.add_command(label=self._t("menubar.open_log"), command=self._menu_action_open_log_folder)
        tools_menu.add_command(label=self._t("menubar.docs"), command=self._open_docs_window)
        self.menubar.add_cascade(label=self._t("menubar.tools"), menu=tools_menu)

        help_menu = tk.Menu(self.menubar, tearoff=0)
        help_menu.add_command(label=self._t("menubar.about"), command=self._open_about_dialog)
        self.menubar.add_cascade(label=self._t("menubar.help"), menu=help_menu)

        self.config(menu=self.menubar)

    def _retranslate_menu_bar(self):
        """Native tk.Menu labels are not widgets, so rebuild the bar on a switch."""
        self._build_menu_bar()

    def _build_status_bar(self):
        status_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=STATUS_BAR_BG, border_width=1, border_color=STATUS_BAR_BORDER)
        status_frame.grid(row=5, column=0, sticky="ew")
        status_frame.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            status_frame,
            text=self._t("status.ready"),
            font=ctk.CTkFont(size=10),
            anchor="w",
            text_color=MUTED_TEXT
        )
        self.status_label.grid(row=0, column=0, padx=8, sticky="w")

        self.ffmpeg_badge = ctk.CTkLabel(
            status_frame,
            text=self._t("ffmpeg.checking"),
            font=ctk.CTkFont(size=10),
            text_color=MUTED_TEXT
        )
        self.ffmpeg_badge.grid(row=0, column=1, padx=8, sticky="e")

        self.api_key_badge = ctk.CTkLabel(
            status_frame,
            text="",
            font=ctk.CTkFont(size=10),
            text_color=MUTED_TEXT
        )
        self.api_key_badge.grid(row=0, column=2, padx=8, sticky="e")

    def _refresh_menu_key_badge(self):
        if self.api_key_badge is None or not self.api_key_badge.winfo_exists():
            return
        if self.api_key_var.get().strip():
            self.api_key_badge.configure(
                text=self._t("statusbar.api_key_configured"),
                text_color=("#15803D", "#4ADE80")
            )
        else:
            self.api_key_badge.configure(
                text=self._t("statusbar.api_key_missing"),
                text_color=("#DC2626", "#F87171")
            )

    # -------------------------------------------------------------
    # Actions reachable from the menu bar and toolbar
    # -------------------------------------------------------------
    def _menu_action_open_log_folder(self):
        folder = LOG_FILE.parent
        try:
            os.startfile(str(folder))
            self._set_status(self._t("status.log_opened", folder=folder))
        except Exception as e:
            log.warning("Could not open log folder: %s", e)
            messagebox.showinfo(self._t("msg.log_folder"), self._t("msg.log_folder_body", folder=folder))

    def _open_docs_window(self):
        """Open (or focus) the in-app documentation reader."""
        existing = getattr(self, "_docs_window", None)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return existing
        self._docs_window = DocsWindow(
            self,
            locale=self.ui_locale,
            on_close=self._forget_docs_window
        )
        return self._docs_window

    def _forget_docs_window(self, window=None):
        if window is None or window is self._docs_window:
            self._docs_window = None

    def _refresh_docs_window(self):
        """Re-label the documentation reader after a UI language switch."""
        window = getattr(self, "_docs_window", None)
        if window is not None and window.winfo_exists():
            window.refresh_locale(self.ui_locale)

    def _open_api_key_page(self):
        """Open Google AI Studio so the user can create a Gemini API key."""
        try:
            opened = webbrowser.open(API_KEY_URL, new=2)
        except Exception as e:
            log.warning("Could not open the API key page: %s", e)
            opened = False
        if opened:
            self._set_status(self._t("status.key_link_opened"))
        else:
            messagebox.showinfo(
                self._t("msg.key_link_title"),
                self._t("msg.key_link_failed", url=API_KEY_URL)
            )

    def _open_settings_dialog(self):
        """Modal holding Gemini API Key entry, processing options and audio preprocessing."""
        existing = getattr(self, "_settings_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return

        dialog = ctk.CTkToplevel(self)
        dialog.withdraw()  # hide until fully built (prevents CTkToplevel ghost-window flicker on Windows)
        self._settings_dialog = dialog
        dialog.title(self._t("settings.title"))
        center_window(dialog, self, 520, 580)
        dialog.minsize(460, 420)
        dialog.transient(self)
        dialog.grab_set()

        # Pinned Bottom Action Section (never pushed off-screen)
        bottom_box = ctk.CTkFrame(dialog, fg_color="transparent", corner_radius=0)
        bottom_box.pack(side="bottom", fill="x", padx=22, pady=(8, 16))
        bottom_box.grid_columnconfigure(1, weight=1)

        def close_dialog(_event=None):
            """Release grab and destroy the settings dialog cleanly."""
            try:
                dialog.grab_release()
            except Exception:
                pass
            if hasattr(key_entry, "_textvariable"):
                key_entry._textvariable = None
            self._settings_dialog = None
            try:
                dialog.destroy()
            except Exception:
                pass

        def do_save():
            if self._save_api_key(notify=False):
                new_prep = bool(temp_preprocess_var.get())
                self.preprocess_var.set(new_prep)
                save_pref("preprocess", new_prep)

                engine = temp_engine_var.get()
                self.engine_var.set(engine)
                save_pref("engine", engine)
                self._on_engine_changed(engine)

                chunk = temp_chunk_var.get()
                self.chunk_size_var.set(chunk)
                save_pref("chunk_minutes", self._parse_chunk_minutes(chunk))

                self._on_template_selected(temp_template_var.get())

                messagebox.showinfo(self._t("msg.success"), self._t("msg.key_saved_body"), parent=dialog)
                close_dialog()

        def do_clear():
            save_api_key("")
            close_dialog()
            self.api_key_var.set("")
            self._refresh_menu_key_badge()
            self._set_status(self._t("status.key_cleared"))
            messagebox.showinfo(self._t("msg.cleared"), self._t("msg.key_cleared_body"))

        ctk.CTkButton(
            bottom_box, text=self._t("settings.clear"), width=105, fg_color=("#C62828", "#B71C1C"),
            hover_color=("#B71C1C", "#8E0000"), command=do_clear, corner_radius=0
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            bottom_box, text=self._t("settings.cancel"), width=95, command=close_dialog, corner_radius=0
        ).grid(row=0, column=2, padx=6, sticky="e")

        ctk.CTkButton(
            bottom_box, text=self._t("settings.save"), width=110, fg_color="#2E7D32", hover_color="#1B5E20",
            font=ctk.CTkFont(weight="bold"), command=do_save, corner_radius=0
        ).grid(row=0, column=3, sticky="e")

        # Divider above buttons
        ctk.CTkFrame(dialog, height=1, fg_color=("gray85", "gray25"), corner_radius=0).pack(
            side="bottom", fill="x", padx=22
        )

        # Scrollable Content Body
        body = ctk.CTkScrollableFrame(dialog, fg_color="transparent", corner_radius=0)
        body.pack(side="top", fill="both", expand=True, padx=16, pady=(16, 6))
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
            placeholder_text=self._t("settings.placeholder"),
            corner_radius=0
        )
        key_entry.grid(row=0, column=0, sticky="ew")

        def toggle_visibility():
            show_state["visible"] = not show_state["visible"]
            key_entry.configure(show="" if show_state["visible"] else "•")
            toggle_btn.configure(text="🙈" if show_state["visible"] else "👁")

        toggle_btn = ctk.CTkButton(
            entry_row,
            text="👁",
            width=42,
            corner_radius=0,
            command=toggle_visibility
        )
        toggle_btn.grid(row=0, column=1, padx=(6, 0))

        get_key_link = ctk.CTkLabel(
            entry_row,
            text=self._t("settings.get_key"),
            font=ctk.CTkFont(size=12, underline=True),
            text_color=("#1976D2", "#64B5F6"),
            cursor="hand2",
            anchor="w"
        )
        get_key_link.grid(row=1, column=0, columnspan=2, pady=(7, 0), sticky="w")
        get_key_link.bind("<Button-1>", lambda _e: self._open_api_key_page())
        get_key_link.bind("<Enter>", lambda _e: get_key_link.configure(text_color=("#0D47A1", "#90CAF9")))
        get_key_link.bind("<Leave>", lambda _e: get_key_link.configure(text_color=("#1976D2", "#64B5F6")))

        ctk.CTkLabel(
            entry_row,
            text=self._t("settings.get_key_hint"),
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w"
        ).grid(row=2, column=0, columnspan=2, pady=(1, 0), sticky="w")

        # Divider between API Key and Audio Preprocessing
        ctk.CTkFrame(body, height=1, fg_color=("gray85", "gray25"), corner_radius=0).grid(
            row=3, column=0, pady=(16, 12), sticky="ew"
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
            corner_radius=0,
            font=ctk.CTkFont(size=13, weight="bold")
        )
        preprocess_chk.grid(row=6, column=0, pady=(10, 4), sticky="w")

        ctk.CTkLabel(
            body,
            text=self._t("settings.preprocess_help"),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            justify="left",
            wraplength=450,
            anchor="w"
        ).grid(row=7, column=0, pady=(0, 6), sticky="ew")

        # Processing Section: engine, chunk duration and minutes format
        ctk.CTkFrame(body, height=1, fg_color=("gray85", "gray25"), corner_radius=0).grid(
            row=8, column=0, pady=(16, 12), sticky="ew"
        )

        ctk.CTkLabel(
            body,
            text=self._t("settings.processing_heading"),
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w"
        ).grid(row=9, column=0, sticky="ew")

        proc_frame = ctk.CTkFrame(body, fg_color="transparent", corner_radius=0)
        proc_frame.grid(row=10, column=0, pady=(10, 0), sticky="ew")
        proc_frame.grid_columnconfigure(1, weight=1)

        def add_proc_row(row_idx, i18n_key):
            ctk.CTkLabel(proc_frame, text=self._t(i18n_key), anchor="w").grid(
                row=row_idx, column=0, pady=6, sticky="w"
            )

        # Engine
        add_proc_row(0, "settings.engine")
        temp_engine_var = ctk.StringVar(value=self.engine_var.get())
        temp_chunk_var = ctk.StringVar(value=self.chunk_size_var.get())
        temp_template_var = ctk.StringVar(value=self.template_display_var.get())

        def on_engine_choice(choice):
            temp_chunk_var.set("25 min")
            chunk_menu.configure(values=self._chunk_display_values())
            if "Auto" in choice:
                self._set_status(self._t("status.engine_auto"))
            else:
                self._set_status(self._t("status.engine_selected", choice=choice.strip()))

        engine_menu = ctk.CTkOptionMenu(
            proc_frame,
            values=list(VALID_ENGINES),
            variable=temp_engine_var,
            corner_radius=0,
            command=on_engine_choice
        )
        engine_menu.grid(row=0, column=1, padx=(10, 0), pady=6, sticky="ew")

        # Chunk duration
        add_proc_row(1, "settings.chunk")
        chunk_menu = ctk.CTkOptionMenu(
            proc_frame,
            values=self._chunk_display_values(),
            variable=temp_chunk_var,
            corner_radius=0
        )
        chunk_menu.grid(row=1, column=1, padx=(10, 0), pady=6, sticky="ew")

        # Speaker ID note beneath chunk dropdown
        lbl_chunk_note = ctk.CTkLabel(
            proc_frame,
            text=self._t("settings.chunk_note"),
            font=ctk.CTkFont(size=11),
            text_color=("gray30", "gray70"),
            justify="left",
            wraplength=450,
            anchor="w"
        )
        lbl_chunk_note.grid(row=2, column=0, columnspan=2, padx=(0, 0), pady=(0, 6), sticky="w")

        # Meeting minute format
        add_proc_row(3, "settings.template")
        ctk.CTkOptionMenu(
            proc_frame,
            values=[display_template_name(k, self.ui_locale) for k in VALID_TEMPLATES],
            variable=temp_template_var,
            corner_radius=0
        ).grid(row=3, column=1, padx=(10, 0), pady=6, sticky="ew")

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        dialog.deiconify()  # now show the fully-built dialog
        dialog.after(50, key_entry.focus_set)

    def _open_audio_setup_wizard_manual(self):
        if not self.selected_audio_file or not os.path.exists(self.selected_audio_file):
            messagebox.showinfo(self._t("msg.notice"), self._t("file.no_selection"), parent=self)
            return
        self._open_audio_setup_wizard(self.selected_audio_file)

    def _open_audio_setup_wizard(self, audio_path: Optional[str] = None):
        target_path = audio_path or self.selected_audio_file
        if not target_path or not os.path.exists(target_path):
            return

        existing = getattr(self, "_wizard_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return

        self.selected_audio_file = target_path
        file_name = Path(target_path).name
        file_size_mb = os.path.getsize(target_path) / (1024 * 1024)

        duration_sec = self.audio_duration_seconds or 0
        if duration_sec <= 0:
            try:
                duration_sec = get_audio_duration(target_path)
                self.audio_duration_seconds = duration_sec
            except Exception:
                duration_sec = 0

        cost_info = estimate_cost_and_tokens(duration_sec) if duration_sec > 0 else {
            "formatted_duration": "00:00:00",
            "estimated_input_tokens": 0,
            "estimated_cost_usd": 0.0,
        }

        # Recommendations based on audio length
        if 0 < duration_sec <= 1200:
            rec_chunk = "15 min" if duration_sec <= 900 else "20 min"
            chunk_hint_key = "wizard.chunk_hint_short"
        else:
            rec_chunk = "25 min"
            chunk_hint_key = "wizard.chunk_hint_long"

        dialog = ctk.CTkToplevel(self)
        dialog.withdraw()  # hide until fully built (prevents CTkToplevel ghost-window flicker on Windows)
        self._wizard_dialog = dialog
        dialog.title(self._t("wizard.title"))
        center_window(dialog, self, 580, 640)
        dialog.minsize(520, 500)
        dialog.transient(self)
        dialog.grab_set()

        # Pinned Bottom Action Section (never cut off)
        bottom_box = ctk.CTkFrame(dialog, fg_color="transparent", corner_radius=0)
        bottom_box.pack(side="bottom", fill="x", padx=22, pady=(8, 16))
        bottom_box.grid_columnconfigure(0, weight=1)

        always_show_var = ctk.BooleanVar(value=bool(get_pref("show_wizard_on_select", True)))
        ctk.CTkCheckBox(
            bottom_box,
            text=self._t("wizard.always_show"),
            variable=always_show_var,
            corner_radius=0,
            font=ctk.CTkFont(size=11),
        ).grid(row=0, column=0, columnspan=3, pady=(0, 10), sticky="w")

        btn_row = ctk.CTkFrame(bottom_box, fg_color="transparent", corner_radius=0)
        btn_row.grid(row=1, column=0, columnspan=3, sticky="ew")
        btn_row.grid_columnconfigure(0, weight=1)

        def close_wizard(_event=None):
            try:
                dialog.grab_release()
            except Exception:
                pass
            self._wizard_dialog = None
            dialog.destroy()

        def apply_and_close(start: bool = False):
            engine = temp_engine_var.get()
            self.engine_var.set(engine)
            save_pref("engine", engine)
            self._on_engine_changed(engine)

            chunk = temp_chunk_var.get()
            self.chunk_size_var.set(chunk)
            save_pref("chunk_minutes", self._parse_chunk_minutes(chunk))

            new_prep = bool(temp_preprocess_var.get())
            self.preprocess_var.set(new_prep)
            save_pref("preprocess", new_prep)

            self._on_template_selected(temp_template_var.get())

            chosen_lang = temp_lang_var.get()
            if chosen_lang in VALID_LANGUAGES:
                self.lang_var.set(chosen_lang)

            save_pref("show_wizard_on_select", bool(always_show_var.get()))
            close_wizard()

            if start:
                self._start_processing_pipeline()

        ctk.CTkButton(
            btn_row,
            text=self._t("wizard.cancel"),
            width=100,
            corner_radius=0,
            command=close_wizard,
        ).grid(row=0, column=1, padx=(0, 10), sticky="e")

        ctk.CTkButton(
            btn_row,
            text=self._t("wizard.start"),
            width=160,
            corner_radius=0,
            fg_color="#2E7D32",
            hover_color="#1B5E20",
            font=ctk.CTkFont(weight="bold"),
            command=lambda: apply_and_close(start=True),
        ).grid(row=0, column=2, sticky="e")

        dialog.protocol("WM_DELETE_WINDOW", close_wizard)
        dialog.deiconify()  # now show the fully-built wizard

        # Divider above buttons
        ctk.CTkFrame(dialog, height=1, fg_color=("gray85", "gray25"), corner_radius=0).pack(
            side="bottom", fill="x", padx=22
        )

        # Scrollable Content Area
        body = ctk.CTkScrollableFrame(dialog, fg_color="transparent", corner_radius=0)
        body.pack(side="top", fill="both", expand=True, padx=16, pady=(16, 6))
        body.grid_columnconfigure(0, weight=1)

        # Header
        ctk.CTkLabel(
            body,
            text=self._t("wizard.heading"),
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(
            body,
            text=self._t("wizard.help"),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            justify="left",
            anchor="w",
            wraplength=500,
        ).grid(row=1, column=0, pady=(4, 12), sticky="ew")

        # Audio Summary Card
        card = ctk.CTkFrame(
            body,
            corner_radius=0,
            border_width=1,
            border_color=("gray80", "gray25"),
            fg_color=("gray95", "gray18"),
        )
        card.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text=f"📁 {file_name} ({file_size_mb:.1f} MB)",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=14, pady=(10, 2), sticky="ew")

        stats_text = self._t(
            "wizard.stats",
            duration=cost_info.get("formatted_duration", "--:--:--"),
            size=f"{file_size_mb:.1f}",
            tokens=f"{cost_info.get('estimated_input_tokens', 0):,}",
        )
        ctk.CTkLabel(
            card,
            text=stats_text,
            font=ctk.CTkFont(size=11),
            text_color=("gray30", "gray70"),
            anchor="w",
        ).grid(row=1, column=0, padx=14, pady=(0, 4), sticky="ew")

        ctk.CTkLabel(
            card,
            text=self._t("wizard.rec_banner"),
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#2E7D32", "#81C784"),
            anchor="w",
        ).grid(row=2, column=0, padx=14, pady=(0, 10), sticky="ew")

        # Configuration Form
        form = ctk.CTkFrame(body, fg_color="transparent", corner_radius=0)
        form.grid(row=3, column=0, sticky="ew")
        form.grid_columnconfigure(1, weight=1)

        def add_field_label(r, text_key):
            ctk.CTkLabel(
                form,
                text=self._t(text_key),
                font=ctk.CTkFont(size=12, weight="bold"),
                anchor="w",
            ).grid(row=r, column=0, pady=5, sticky="w")

        # 1. Engine
        add_field_label(0, "wizard.engine")
        temp_engine_var = ctk.StringVar(value=self.engine_var.get() or "⚡ Gemini Cloud (Auto-Failover)")
        ctk.CTkOptionMenu(
            form,
            values=list(VALID_ENGINES),
            variable=temp_engine_var,
            corner_radius=0,
        ).grid(row=0, column=1, padx=(10, 0), pady=5, sticky="ew")

        # 2. Chunk duration
        add_field_label(1, "wizard.chunk")
        temp_chunk_var = ctk.StringVar(value=rec_chunk)
        ctk.CTkOptionMenu(
            form,
            values=self._chunk_display_values(),
            variable=temp_chunk_var,
            corner_radius=0,
        ).grid(row=1, column=1, padx=(10, 0), pady=5, sticky="ew")

        ctk.CTkLabel(
            form,
            text=self._t(chunk_hint_key),
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
        ).grid(row=2, column=1, padx=(10, 0), pady=(0, 6), sticky="w")

        # 3. Preprocess
        temp_preprocess_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            form,
            text=self._t("wizard.preprocess"),
            variable=temp_preprocess_var,
            corner_radius=0,
            font=ctk.CTkFont(size=12),
        ).grid(row=3, column=0, columnspan=2, pady=6, sticky="w")

        # 4. Minutes format
        add_field_label(4, "wizard.template")
        temp_template_var = ctk.StringVar(value=self.template_display_var.get())
        ctk.CTkOptionMenu(
            form,
            values=[display_template_name(k, self.ui_locale) for k in VALID_TEMPLATES],
            variable=temp_template_var,
            corner_radius=0,
        ).grid(row=4, column=1, padx=(10, 0), pady=5, sticky="ew")

        # 5. Output Language
        add_field_label(5, "wizard.language")
        temp_lang_var = ctk.StringVar(value=self.lang_var.get() or "English")
        ctk.CTkOptionMenu(
            form,
            values=list(VALID_LANGUAGES),
            variable=temp_lang_var,
            corner_radius=0,
        ).grid(row=5, column=1, padx=(10, 0), pady=5, sticky="ew")

    def _open_about_dialog(self):
        ffmpeg_ok, _ = check_ffmpeg()
        dialog = ctk.CTkToplevel(self)
        dialog.withdraw()  # hide until fully built (prevents CTkToplevel ghost-window flicker on Windows)
        dialog.title(self._t("about.title"))
        center_window(dialog, self, 480, 420)
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
        dialog.deiconify()  # now show the fully-built about dialog

    def _build_file_section(self):
        file_frame = ctk.CTkFrame(self, corner_radius=0)
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

        self.wizard_btn = ctk.CTkButton(
            file_frame,
            text=self._t("file.wizard"),
            command=self._open_audio_setup_wizard_manual,
            width=140,
            corner_radius=0,
            font=ctk.CTkFont(size=12),
            state="disabled"
        )
        self.wizard_btn.grid(row=0, column=2, padx=(6, 16), pady=12, sticky="e")
        self._i18n_label(self.wizard_btn, "file.wizard")

        # Audio Info Row
        self.audio_stats_label = ctk.CTkLabel(
            file_frame,
            text=self._t("file.stats_placeholder"),
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.audio_stats_label.grid(row=1, column=0, columnspan=3, padx=16, pady=(0, 10), sticky="w")

    def _build_controls_section(self):
        ctrl_frame = ctk.CTkFrame(self, corner_radius=0)
        ctrl_frame.grid(row=2, column=0, padx=16, pady=6, sticky="ew")
        ctrl_frame.grid_columnconfigure(2, weight=1)

        # Engine / chunk / minutes format now live in the Settings modal. Only the
        # backing variables stay here so the pipeline and session restore keep working.
        self.engine_var = ctk.StringVar(
            value=normalize_settings({"engine": get_pref("engine")})["engine"]
        )
        pref_chunk = normalize_settings({'chunk_minutes': get_pref('chunk_minutes')})['chunk_minutes']
        initial_chunk_val = self._t("chunk.no_chunk") if pref_chunk == 0 else f"{pref_chunk} min"
        self.chunk_size_var = ctk.StringVar(value=initial_chunk_val)

        self.template_display_var = ctk.StringVar(
            value=display_template_name(self.template_var.get(), self.ui_locale)
        )

        # Pre-process state: persisted across restarts via prefs.json, edited in Settings modal
        self.preprocess_var = ctk.BooleanVar(value=bool(get_pref("preprocess", True)))

        # Action Buttons (Workflow Triggers)
        self.start_btn = ctk.CTkButton(
            ctrl_frame,
            text=self._t("btn.transcribe"),
            fg_color="#2E7D32",
            hover_color="#1B5E20",
            font=ctk.CTkFont(weight="bold"),
            command=self._start_processing_pipeline,
            width=150
        )
        self.start_btn.grid(row=0, column=3, padx=4, pady=10, sticky="e")
        self._i18n_label(self.start_btn, "btn.transcribe")

        self.cancel_btn = ctk.CTkButton(
            ctrl_frame,
            text=self._t("btn.cancel"),
            fg_color="#C62828",
            hover_color="#B71C1C",
            command=self._cancel_processing,
            state="disabled",
            width=85
        )
        self.cancel_btn.grid(row=0, column=4, padx=4, pady=10, sticky="e")
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
        self.monitor_btn.grid(row=0, column=5, padx=4, pady=10, sticky="e")
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
        self.reset_btn.grid(row=0, column=6, padx=(4, 16), pady=10, sticky="e")
        self._i18n_label(self.reset_btn, "btn.reset")

        # Visual Stepper Bar
        self.stepper_frame = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        self.stepper_frame.grid(row=1, column=0, columnspan=14, padx=16, pady=(4, 4), sticky="ew")
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
                corner_radius=0,
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
        self.progress_bar.grid(row=2, column=0, columnspan=14, padx=16, pady=(4, 4), sticky="ew")
        self.progress_bar.set(0.0)

        self.status_label = ctk.CTkLabel(
            ctrl_frame,
            text=self._t("status.ready"),
            font=ctk.CTkFont(size=12),
            anchor="w"
        )
        self.status_label.grid(row=3, column=0, columnspan=14, padx=16, pady=(0, 10), sticky="w")

        # The toolbar was built before these buttons existed; link their states.
        self._wire_toolbar_state()

    def _build_tabs_section(self):
        self.tabview = ctk.CTkTabview(self, corner_radius=0)
        self.tabview.grid(row=3, column=0, padx=16, pady=6, sticky="nsew")

        # Tabs are added under locale-independent names so switching language
        # never changes tab identity; only the captions are re-labelled.
        self.tab_transcript = self.tabview.add("tab_transcript")
        self.tab_minutes = self.tabview.add("tab_minutes")
        self.tab_recap = self.tabview.add("tab_recap")
        self.tab_actions = self.tabview.add("tab_actions")
        self._retranslate_tabs()

        # Setup textboxes in each tab
        self.txt_transcript = self._create_textbox(self.tab_transcript)

        # Minutes tab with top inline retry banner
        self.tab_minutes.grid_columnconfigure(0, weight=1)
        self.tab_minutes.grid_rowconfigure(2, weight=1)

        self.minutes_banner_frame = ctk.CTkFrame(self.tab_minutes, fg_color=("#FFEBEE", "#421C1C"), corner_radius=0)
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

        # Minutes Toolbar
        minutes_toolbar = ctk.CTkFrame(self.tab_minutes, fg_color="transparent")
        minutes_toolbar.grid(row=1, column=0, sticky="ew", padx=6, pady=(6, 2))
        minutes_toolbar.grid_columnconfigure(3, weight=1)

        self.gen_minutes_btn = ctk.CTkButton(
            minutes_toolbar,
            text=self._t("btn.generate_minutes"),
            fg_color="#1976D2",
            hover_color="#1565C0",
            font=ctk.CTkFont(weight="bold"),
            command=self._start_minutes_generation_only,
            state="disabled",
            width=160
        )
        self.gen_minutes_btn.grid(row=0, column=0, padx=4, sticky="w")
        self._i18n_label(self.gen_minutes_btn, "btn.generate_minutes")

        tmpl_tab_lbl = ctk.CTkLabel(
            minutes_toolbar,
            text=self._t("control.template"),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        tmpl_tab_lbl.grid(row=0, column=1, padx=(16, 6), sticky="w")
        self._i18n_label(tmpl_tab_lbl, "control.template")

        self.tab_template_dropdown = ctk.CTkOptionMenu(
            minutes_toolbar,
            values=[display_template_name(k, self.ui_locale) for k in VALID_TEMPLATES],
            variable=self.template_display_var,
            width=220,
            command=self._on_template_selected
        )
        self.tab_template_dropdown.grid(row=0, column=2, padx=4, sticky="w")

        # Note: self.minutes_banner_frame starts hidden (gridded on row 0 when error occurs)

        self.txt_minutes = MarkdownViewer(self.tab_minutes, wrap="word")
        self.txt_minutes.grid(row=2, column=0, sticky="nsew", padx=6, pady=6)

        # Recap tab with top toolbar and inline error banner
        self.tab_recap.grid_columnconfigure(0, weight=1)
        self.tab_recap.grid_rowconfigure(2, weight=1)

        self.recap_banner_frame = ctk.CTkFrame(self.tab_recap, fg_color=("#FFEBEE", "#421C1C"), corner_radius=0)
        self.recap_banner_label = ctk.CTkLabel(
            self.recap_banner_frame,
            text="",
            text_color=("#C62828", "#FFCDD2"),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.recap_banner_label.pack(side="left", padx=12, pady=6)

        self.retry_recap_btn = ctk.CTkButton(
            self.recap_banner_frame,
            text=self._t("btn.retry_recap"),
            fg_color="#D32F2F",
            hover_color="#B71C1C",
            width=140,
            command=self._start_recap_generation_only
        )
        self.retry_recap_btn.pack(side="right", padx=12, pady=6)

        recap_toolbar = ctk.CTkFrame(self.tab_recap, fg_color="transparent")
        recap_toolbar.grid(row=1, column=0, sticky="ew", padx=6, pady=(6, 2))
        recap_toolbar.grid_columnconfigure(1, weight=1)

        self.gen_recap_btn = ctk.CTkButton(
            recap_toolbar,
            text=self._t("btn.generate_recap"),
            fg_color="#2E7D32",
            hover_color="#1B5E20",
            font=ctk.CTkFont(weight="bold"),
            command=self._start_recap_generation_only,
            state="disabled",
            width=160
        )
        self.gen_recap_btn.grid(row=0, column=0, padx=4, sticky="w")
        self._i18n_label(self.gen_recap_btn, "btn.generate_recap")

        self.txt_recap = MarkdownViewer(self.tab_recap, wrap="word")
        self.txt_recap.grid(row=2, column=0, sticky="nsew", padx=6, pady=6)

        # Action Items tab with top toolbar and inline error banner
        self.tab_actions.grid_columnconfigure(0, weight=1)
        self.tab_actions.grid_rowconfigure(2, weight=1)

        self.actions_banner_frame = ctk.CTkFrame(self.tab_actions, fg_color=("#FFEBEE", "#421C1C"), corner_radius=0)
        self.actions_banner_label = ctk.CTkLabel(
            self.actions_banner_frame,
            text="",
            text_color=("#C62828", "#FFCDD2"),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.actions_banner_label.pack(side="left", padx=12, pady=6)

        self.retry_actions_btn = ctk.CTkButton(
            self.actions_banner_frame,
            text=self._t("btn.retry_actions"),
            fg_color="#D32F2F",
            hover_color="#B71C1C",
            width=140,
            command=self._start_actions_generation_only
        )
        self.retry_actions_btn.pack(side="right", padx=12, pady=6)

        actions_toolbar = ctk.CTkFrame(self.tab_actions, fg_color="transparent")
        actions_toolbar.grid(row=1, column=0, sticky="ew", padx=6, pady=(6, 2))
        actions_toolbar.grid_columnconfigure(1, weight=1)

        self.gen_actions_btn = ctk.CTkButton(
            actions_toolbar,
            text=self._t("btn.generate_actions"),
            fg_color="#00897B",
            hover_color="#00695C",
            font=ctk.CTkFont(weight="bold"),
            command=self._start_actions_generation_only,
            state="disabled",
            width=180
        )
        self.gen_actions_btn.grid(row=0, column=0, padx=4, sticky="w")
        self._i18n_label(self.gen_actions_btn, "btn.generate_actions")

        self.txt_actions = MarkdownViewer(self.tab_actions, wrap="word")
        self.txt_actions.grid(row=2, column=0, sticky="nsew", padx=6, pady=6)

    def _create_textbox(self, parent_tab):
        parent_tab.grid_columnconfigure(0, weight=1)
        parent_tab.grid_rowconfigure(0, weight=1)
        tb = ctk.CTkTextbox(parent_tab, wrap="word", font=ctk.CTkFont(family="Consolas", size=12))
        tb.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        return tb

    def _build_bottom_bar(self):
        bottom_frame = ctk.CTkFrame(self, corner_radius=0)
        bottom_frame.grid(row=4, column=0, padx=16, pady=(6, 12), sticky="ew")
        bottom_frame.grid_columnconfigure(1, weight=1)

        # Speaker mapping trigger
        self.speaker_btn = ctk.CTkButton(
            bottom_frame,
            text=self._t("btn.map_speakers"),
            command=self._open_speaker_mapping_dialog,
            state="disabled",
            width=160
        )
        self.speaker_btn.grid(row=0, column=0, padx=16, pady=10, sticky="w")
        self._i18n_label(self.speaker_btn, "btn.map_speakers")

        # Export Buttons
        export_docx_btn = ctk.CTkButton(
            bottom_frame,
            text=self._t("btn.export_docx"),
            command=lambda: self._export_document("docx"),
            width=150
        )
        export_docx_btn.grid(row=0, column=2, padx=4, pady=10)
        self._i18n_label(export_docx_btn, "btn.export_docx")

        export_txt_btn = ctk.CTkButton(
            bottom_frame,
            text=self._t("btn.export_txt"),
            command=lambda: self._export_document("txt"),
            width=130
        )
        export_txt_btn.grid(row=0, column=3, padx=4, pady=10)
        self._i18n_label(export_txt_btn, "btn.export_txt")

        export_all_btn = ctk.CTkButton(
            bottom_frame,
            text=self._t("btn.export_all"),
            fg_color="#1565C0",
            hover_color="#0D47A1",
            command=lambda: self._export_document("all"),
            width=110
        )
        export_all_btn.grid(row=0, column=4, padx=(4, 16), pady=10)
        self._i18n_label(export_all_btn, "btn.export_all")

    # -------------------------------------------------------------
    # Helpers & Validation
    # -------------------------------------------------------------
    def _check_initial_environment(self):
        is_ok, _msg = check_ffmpeg()
        self._ffmpeg_ok: Optional[bool] = is_ok
        self._refresh_ffmpeg_badge()
        if not is_ok:
            messagebox.showwarning(
                self._t("msg.ffmpeg_warning"),
                self._t("msg.ffmpeg_missing_body")
            )

    def _refresh_ffmpeg_badge(self):
        """Render the FFmpeg status indicator for the active language."""
        if getattr(self, "_ffmpeg_ok", None) is None:
            return
        if self._ffmpeg_ok:
            self.ffmpeg_badge.configure(
                text=self._t("ffmpeg.installed"), text_color="#2E7D32"
            )
        else:
            self.ffmpeg_badge.configure(
                text=self._t("ffmpeg.missing"), text_color="#C62828"
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
                )
            )
        except Exception as e:
            self.file_label.configure(text=self._t("file.selected", name=file_name))
            self.audio_stats_label.configure(text=self._t("file.stats_error", error=e))

        # A valid file is now loaded: the session can be saved even if none exists yet
        self._set_save_session_enabled(True)
        if hasattr(self, "wizard_btn"):
            self.wizard_btn.configure(state="normal")

        # Auto-restore previous completed session if exists
        restored = self._load_full_session_if_exists(chosen)
        if not restored and get_pref("show_wizard_on_select", True):
            self.after(150, lambda: self._open_audio_setup_wizard(chosen))

    def _get_selected_model_override(self) -> Optional[str]:
        """Returns the specific Gemini model string if selected, or None for Auto-Failover."""
        choice = self.engine_var.get()
        if "Flash Lite" in choice:
            return "gemini-3.5-flash-lite"
        elif "3.8 Flash" in choice:
            return "gemini-3.8-flash"
        elif "3.5 Flash" in choice:
            return "gemini-3.5-flash"
        return None

    def _is_diarization_supported(
        self,
        chunk_mins: Optional[int] = None,
        engine_choice: Optional[str] = None
    ) -> bool:
        """
        Returns True only if:
        1. No chunking is selected (chunk_minutes <= 0).
        2. The engine is not a weak model (e.g. Gemini 3.5 Flash Lite).
        """
        if chunk_mins is None:
            chunk_mins = self._parse_chunk_minutes(self.chunk_size_var.get())
        if engine_choice is None:
            engine_choice = self.engine_var.get()
        if chunk_mins > 0:
            return False
        if "Flash Lite" in str(engine_choice) or "lite" in str(engine_choice).lower():
            return False
        return True

    def _on_engine_changed(self, choice: str):
        """Reset chunking back to the default whenever the engine changes."""
        self.chunk_size_var.set("25 min")
        if "Auto" in choice:
            self._set_status(self._t("status.engine_auto"))
        else:
            self._set_status(self._t("status.engine_selected", choice=choice.strip()))

    def _on_template_selected(self, display_choice: str):
        """Map localized template selection back to canonical template key and persist."""
        for k in VALID_TEMPLATES:
            if display_template_name(k, self.ui_locale) == display_choice:
                self.template_var.set(k)
                save_pref("template", k)
                log.info("Meeting minute template changed to: %s", k)

                # If this template was already generated and cached, load it instantly into view
                cached_text = self.cached_minutes_by_template.get(k)
                if cached_text:
                    self.generated_minutes = cached_text
                    sections = parse_minutes_sections(cached_text)
                    self._populate_minutes_tabs(sections)
                    self._hide_minutes_error_banner()
                else:
                    # Switch to empty view for this template so user can click Generate
                    self.generated_minutes = ""
                    self.txt_minutes.delete("1.0", "end")

                # If transcript is available and pipeline is not busy, enable Generate Minutes button
                has_transcript = bool((self.processed_transcript or self.raw_transcript).strip())
                if has_transcript and not self.is_processing:
                    self.gen_minutes_btn.configure(state="normal")
                break

    def _chunk_display_values(self):
        """Chunk options rendered as localized 'No Chunking (Single File)' or '<minutes> min'."""
        values = []
        for mins in VALID_CHUNK_MINUTES:
            if mins == 0:
                values.append(self._t("chunk.no_chunk"))
            else:
                values.append(f"{mins} min")
        return values

    def _parse_chunk_minutes(self, display_val: str) -> int:
        """Parse chunk minutes integer from display text."""
        raw = str(display_val).strip()
        if raw == self._t("chunk.no_chunk") or "No Chunk" in raw or "Tiada" in raw or raw.startswith("0"):
            return 0
        try:
            return int(raw.split()[0])
        except (ValueError, IndexError):
            return DEFAULT_CHUNK_MINUTES

    def _refresh_template_dropdown(self):
        """Refresh template dropdown labels according to current UI locale."""
        if hasattr(self, "template_display_var"):
            new_values = [display_template_name(k, self.ui_locale) for k in VALID_TEMPLATES]
            if hasattr(self, "tab_template_dropdown"):
                self.tab_template_dropdown.configure(values=new_values)
            self.template_display_var.set(display_template_name(self.template_var.get(), self.ui_locale))

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
        self._transcribing = True
        self.cancel_event.clear()
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress_bar.set(0.0)
        self._reset_all_step_badges()
        self._session_settings_snapshot = None

        # Clear text displays
        for tb in [self.txt_transcript, self.txt_minutes, self.txt_recap, self.txt_actions]:
            tb.delete("1.0", "end")

        chunk_mins = self._parse_chunk_minutes(self.chunk_size_var.get())
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

    def _cancel_processing(self, parent=None):
        """Immediately raise the cooperative cancel flag to stop all processing."""
        if not self.is_processing and not self._transcribing:
            messagebox.showinfo(
                self._t("msg.cancel_title"),
                self._t("msg.cancel_nothing"),
                parent=parent or self
            )
            return

        self.cancel_event.set()
        self._set_status(self._t("status.cancelling"))
        self.cancel_btn.configure(state="disabled")

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
        # Closing is blocked only while a transcription run is in flight. Because
        # the dialog is rebuilt here, this line also clears any stale lock.
        self.monitor_dialog.set_close_locked(self._transcribing)
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
                # Runs on the worker thread; the handler touches Tk widgets.
                self.after(0, self._on_pipeline_cancelled)
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
                    self.after(0, self._on_pipeline_cancelled)
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
                    can_diarize = self._is_diarization_supported(chunk_minutes, self.engine_var.get())
                    raw_chunk_text = transcribe_audio_chunk(
                        client=client,
                        chunk_file_path=chunk_info["file_path"],
                        previous_tail_transcript=previous_tail_context,
                        progress_callback=lambda msg: self._set_status(
                            self._t("status.step_chunk", chunk=chunk_display, msg=msg)
                        ),
                        model_override=model_override,
                        cancel_event=self.cancel_event,
                        diarize=can_diarize
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

                except CancelledError:
                    # A cancel is not a chunk failure: leave the chunk pending so
                    # the next run resumes it, and unwind the whole pipeline.
                    self._update_chunk_monitor_item(idx, "cancelled")
                    self.after(0, self._on_pipeline_cancelled)
                    return

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
            self._transcribing = False
            self.after(0, lambda: self.start_btn.configure(state="normal"))
            self.after(0, lambda: self.cancel_btn.configure(state="disabled"))
            self.after(0, self._unlock_monitor)

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

        self.cancel_event.clear()
        self.is_processing = True
        self.cancel_btn.configure(state="normal")
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

                chunk_mins = self._parse_chunk_minutes(self.chunk_size_var.get())
                can_diarize = self._is_diarization_supported(chunk_mins, self.engine_var.get())
                raw_text = transcribe_audio_chunk(
                    client=client,
                    chunk_file_path=chunk_info["file_path"],
                    previous_tail_transcript=tail_context,
                    model_override=getattr(self, "active_model_override", None),
                    cancel_event=self.cancel_event,
                    diarize=can_diarize
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

            except CancelledError:
                log.info("Reprocess of chunk %d cancelled by user.", chunk_index)
                self.active_chunk_status[chunk_index] = {
                    "status": "cancelled",
                    "text": "",
                    "error": "Cancelled by user"
                }
                self._update_chunk_monitor_item(chunk_index, "cancelled")
                self._set_status(self._t("status.cancelled"))

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
            finally:
                self.is_processing = False
                self.after(0, lambda: self.cancel_btn.configure(state="disabled"))
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
        self.gen_recap_btn.configure(state="normal")
        self.gen_actions_btn.configure(state="normal")

        # Speaker identification is only enabled if No Chunking was selected and model is capable
        if self._is_diarization_supported() and self.detected_speakers:
            self.speaker_btn.configure(state="normal")
        else:
            self.speaker_btn.configure(state="disabled")

        # Save meeting session so it restores across app restarts
        if self.active_file_hash:
            self._save_full_session(self.active_file_hash)

        # Minimize / close monitor
        if self.monitor_dialog and self.monitor_dialog.winfo_exists():
            self.monitor_dialog.set_close_locked(False)
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

            template = self.template_var.get()
            self.generated_minutes = generate_meeting_minutes(
                client=client,
                full_transcript=transcript_to_use,
                language=language,
                template=template,
                progress_callback=lambda msg: self._set_status(
                    f"{self._t('status.step_prefix', n=4)} {msg}"
                ),
                model_override=self._get_selected_model_override(),
                cancel_event=self.cancel_event
            )

            sections = parse_minutes_sections(self.generated_minutes)
            self.cached_minutes_by_template[template] = self.generated_minutes
            self.after(0, lambda secs=sections: self._populate_minutes_tabs(secs))
            self.after(0, self._hide_minutes_error_banner)
            self._update_step_badge("step4", "done")
            self._save_full_session(file_hash)
            self._set_progress(1.0, self._t("status.all_complete"))
            self.after(0, self._on_pipeline_finished)

        except CancelledError:
            # Cancellation is not a synthesis failure: leave the transcript and
            # badges untouched so the user can retry cleanly.
            log.info("Minutes synthesis cancelled by user.")
            self.is_processing = False
            self._transcribing = False
            self._update_step_badge("step4", "pending")
            self._set_status(self._t("status.cancelled"))
            self.after(0, lambda: self.cancel_btn.configure(state="disabled"))

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

        current_template = self.template_var.get()
        # If this template was already generated, warn the user before overwriting
        if current_template in self.cached_minutes_by_template or (self.generated_minutes and self.generated_minutes.strip()):
            template_label = display_template_name(current_template, self.ui_locale)
            confirm = messagebox.askyesno(
                self._t("msg.notice"),
                self._t("msg.minutes_already_generated", template=template_label)
            )
            if not confirm:
                return

        self.is_processing = True
        self.cancel_event.clear()
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

    def _start_recap_generation_only(self):
        """
        Independent trigger for Executive Meeting Recap.
        Enables user to generate or retry meeting recap from existing transcript.
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
        self.cancel_event.clear()
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="disabled")
        self.gen_recap_btn.configure(state="disabled")
        self._hide_recap_error_banner()

        language = self.lang_var.get()
        file_hash = compute_file_hash(self.selected_audio_file) if self.selected_audio_file else "manual_session"

        def runner():
            try:
                self._set_status(self._t("status.generating_recap", language=display_minutes_lang(language, self.ui_locale)))
                client = get_gemini_client(api_key)
                recap_text = generate_meeting_recap(
                    client=client,
                    full_transcript=transcript_to_use,
                    language=language,
                    progress_callback=lambda msg: self._set_status(f"[Recap] {msg}"),
                    model_override=self._get_selected_model_override(),
                    cancel_event=self.cancel_event
                )
                self.generated_recap = recap_text
                self.after(0, lambda: self._update_recap_view(recap_text))
                self.after(0, self._hide_recap_error_banner)
                if file_hash:
                    self._save_full_session(file_hash)
                self._set_status(self._t("status.recap_complete"))
            except CancelledError:
                log.info("Recap synthesis cancelled by user.")
                self._set_status(self._t("status.cancelled"))
            except Exception as e:
                err_msg = str(e)
                log.error("Recap generation failed: %s", err_msg)
                self.after(0, lambda msg=err_msg: self._show_recap_error_banner(msg))
                self._set_status(self._t("status.recap_failed", error=err_msg[:40]))
            finally:
                self.is_processing = False
                self.after(0, lambda: self.start_btn.configure(state="normal"))
                self.after(0, lambda: self.gen_recap_btn.configure(state="normal"))

        t = threading.Thread(target=runner, daemon=True)
        t.start()

    def _start_actions_generation_only(self):
        """
        Independent trigger for Action Items.
        Enables user to generate or retry action items directly from existing transcript.
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
        self.cancel_event.clear()
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="disabled")
        self.gen_actions_btn.configure(state="disabled")
        self._hide_actions_error_banner()

        language = self.lang_var.get()
        file_hash = compute_file_hash(self.selected_audio_file) if self.selected_audio_file else "manual_session"

        def runner():
            try:
                self._set_status(self._t("status.generating_actions", language=display_minutes_lang(language, self.ui_locale)))
                client = get_gemini_client(api_key)
                actions_text = generate_action_items(
                    client=client,
                    full_transcript=transcript_to_use,
                    language=language,
                    progress_callback=lambda msg: self._set_status(f"[Actions] {msg}"),
                    model_override=self._get_selected_model_override(),
                    cancel_event=self.cancel_event
                )
                self.generated_actions = actions_text
                self.after(0, lambda: self._update_actions_view(actions_text))
                self.after(0, self._hide_actions_error_banner)
                if file_hash:
                    self._save_full_session(file_hash)
                self._set_status(self._t("status.actions_complete"))
            except CancelledError:
                log.info("Action items synthesis cancelled by user.")
                self._set_status(self._t("status.cancelled"))
            except Exception as e:
                err_msg = str(e)
                log.error("Action items generation failed: %s", err_msg)
                self.after(0, lambda msg=err_msg: self._show_actions_error_banner(msg))
                self._set_status(self._t("status.actions_failed", error=err_msg[:40]))
            finally:
                self.is_processing = False
                self.after(0, lambda: self.start_btn.configure(state="normal"))
                self.after(0, lambda: self.gen_actions_btn.configure(state="normal"))

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
        chunk_mins = self._parse_chunk_minutes(self.chunk_size_var.get())
        return {
            "engine": self.engine_var.get(),
            "language": self.lang_var.get(),
            "chunk_minutes": chunk_mins,
            "preprocess": bool(self.preprocess_var.get()),
            "template": self.template_var.get(),
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
            generated_recap=self.generated_recap,
            generated_actions=self.generated_actions,
            detected_speakers=self.detected_speakers,
            speaker_mapping=self.speaker_mapping,
            cached_minutes_by_template=self.cached_minutes_by_template
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
        """Toggle the Save Session toolbar button; safe to call from the worker thread."""
        def apply():
            tb_save = getattr(self, "tb_buttons", {}).get("toolbar.save")
            if tb_save is not None and tb_save.winfo_exists():
                tb_save.configure(state="normal" if enabled else "disabled")
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
            self.generated_recap = data.get("generated_recap", "") or ""
            self.generated_actions = data.get("generated_actions", "") or ""
            self.cached_minutes_by_template = dict(data.get("cached_minutes_by_template", {}) or {})
            # If a legacy session has generated_minutes but empty cached_minutes_by_template, backfill it
            saved_template = data.get("settings", {}).get("template", "action_minutes")
            if self.generated_minutes and saved_template not in self.cached_minutes_by_template:
                self.cached_minutes_by_template[saved_template] = self.generated_minutes

            self.detected_speakers = data["detected_speakers"]
            self.speaker_mapping = data["speaker_mapping"]
            self.active_file_hash = audio_hash
            self._set_save_session_enabled(True)

            self._apply_saved_settings(data["settings"])
            self._apply_saved_status(data["status"])

            if self.processed_transcript:
                self._update_transcript_view(self.processed_transcript)
                self.gen_minutes_btn.configure(state="normal")
                self.gen_recap_btn.configure(state="normal")
                self.gen_actions_btn.configure(state="normal")
                saved_chunk_mins = data.get("settings", {}).get("chunk_minutes", DEFAULT_CHUNK_MINUTES)
                saved_engine = data.get("settings", {}).get("engine", "")
                if self._is_diarization_supported(saved_chunk_mins, saved_engine) and self.detected_speakers:
                    self.speaker_btn.configure(state="normal")
                else:
                    self.speaker_btn.configure(state="disabled")

            if self.generated_minutes:
                sections = parse_minutes_sections(self.generated_minutes)
                self._populate_minutes_tabs(sections)
                self._hide_minutes_error_banner()

            if self.generated_recap:
                self._update_recap_view(self.generated_recap)
                self._hide_recap_error_banner()

            if self.generated_actions:
                self._update_actions_view(self.generated_actions)
                self._hide_actions_error_banner()

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
        chunk_val = self._t("chunk.no_chunk") if clean["chunk_minutes"] == 0 else f"{clean['chunk_minutes']} min"
        self.chunk_size_var.set(chunk_val)
        self.preprocess_var.set(clean["preprocess"])
        if "template" in clean and clean["template"] in VALID_TEMPLATES:
            self.template_var.set(clean["template"])
            self._refresh_template_dropdown()
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
            self.gen_recap_btn.configure(state="normal")
            self.gen_actions_btn.configure(state="normal")

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
        for tb in [self.txt_transcript, self.txt_minutes, self.txt_recap, self.txt_actions]:
            tb.delete("1.0", "end")

        # Clear memory state
        self.raw_transcript = ""
        self.processed_transcript = ""
        self.generated_minutes = ""
        self.generated_recap = ""
        self.generated_actions = ""
        self.cached_minutes_by_template = {}
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
        self._hide_recap_error_banner()
        self._hide_actions_error_banner()
        self.gen_minutes_btn.configure(state="disabled")
        self.gen_recap_btn.configure(state="disabled")
        self.gen_actions_btn.configure(state="disabled")
        self.monitor_btn.configure(state="disabled")
        if hasattr(self, "wizard_btn"):
            self.wizard_btn.configure(state="disabled")
        self.active_file_hash = ""
        self._set_save_session_enabled(False)

        # Close floating monitor dialog if open
        if self.monitor_dialog and self.monitor_dialog.winfo_exists():
            self.monitor_dialog.destroy()
        self.monitor_dialog = None
        self._docs_window = None

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

    def _show_recap_error_banner(self, err_msg: str):
        self.recap_banner_label.configure(
            text=self._t("recap.banner_error", error=err_msg[:60])
        )
        self.recap_banner_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 2))

    def _hide_recap_error_banner(self):
        self.recap_banner_frame.grid_forget()

    def _show_actions_error_banner(self, err_msg: str):
        self.actions_banner_label.configure(
            text=self._t("actions.banner_error", error=err_msg[:60])
        )
        self.actions_banner_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 2))

    def _hide_actions_error_banner(self):
        self.actions_banner_frame.grid_forget()

    def _update_recap_view(self, text: str):
        self.txt_recap.set_markdown(text)

    def _update_actions_view(self, text: str):
        self.txt_actions.set_markdown(text)

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
        self.txt_minutes.set_markdown(sections.get("full_text", ""))

    def _on_pipeline_finished(self):
        self.is_processing = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.gen_minutes_btn.configure(state="normal")
        self.gen_recap_btn.configure(state="normal")
        self.gen_actions_btn.configure(state="normal")
        messagebox.showinfo(
            self._t("msg.completed"),
            self._t("msg.completed_body")
        )

    def _unlock_monitor(self):
        """Allow the chunk monitor to be closed again. Main thread only."""
        dialog = self.monitor_dialog
        if dialog is not None and dialog.winfo_exists():
            dialog.set_close_locked(False)

    def _on_pipeline_cancelled(self):
        self.is_processing = False
        self._transcribing = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        # Cancellation can land before this run's monitor exists, in which case
        # the previous run's monitor is the one still holding the lock.
        self._unlock_monitor()
        self._set_status(self._t("status.cancelled"))
        if self.active_file_hash:
            self._save_full_session(self.active_file_hash)

    def _on_pipeline_error(self, error_message: str):
        self.is_processing = False
        self._transcribing = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self._unlock_monitor()
        self._set_status(self._t("status.error", error=error_message))
        messagebox.showerror(
            self._t("msg.transcription_error"),
            self._t("msg.transcription_error_body", error=error_message)
        )

    # -------------------------------------------------------------
    # Speaker Mapping Dialog
    # -------------------------------------------------------------
    def _open_speaker_mapping_dialog(self):
        engine_choice = self.engine_var.get()
        if "Flash Lite" in engine_choice or "lite" in engine_choice.lower():
            messagebox.showinfo(self._t("msg.speaker_mapping"), self._t("msg.speaker_mapping_weak_model"))
            return

        chunk_mins = self._parse_chunk_minutes(self.chunk_size_var.get())
        if chunk_mins > 0:
            messagebox.showinfo(self._t("msg.speaker_mapping"), self._t("msg.speaker_mapping_no_chunk"))
            return

        if not self.raw_transcript:
            messagebox.showinfo(self._t("msg.speaker_mapping"), self._t("msg.no_speakers_yet"))
            return

        speakers = self.detected_speakers or extract_speakers(self.raw_transcript)
        if not speakers:
            messagebox.showinfo(self._t("msg.speaker_mapping"), self._t("msg.no_speakers"))
            return

        dialog = ctk.CTkToplevel(self)
        dialog.withdraw()  # hide until fully built (prevents CTkToplevel ghost-window flicker on Windows)
        dialog.title(self._t("speakers.title"))
        center_window(dialog, self, 450, 380)
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

        # Pinned Bottom Action Section
        bottom_box = ctk.CTkFrame(dialog, fg_color="transparent", corner_radius=0)
        bottom_box.pack(side="bottom", fill="x", padx=16, pady=(6, 12))

        def close_dialog():
            try:
                dialog.grab_release()
            except Exception:
                pass
            dialog.destroy()

        def apply_mapping():
            mapping = {spk: entry.get().strip() for spk, entry in entry_map.items() if entry.get().strip()}
            if not mapping:
                close_dialog()
                return

            self.speaker_mapping = dict(mapping)
            self.processed_transcript = apply_speaker_mapping(self.raw_transcript, mapping)
            self._update_transcript_view(self.processed_transcript)

            if self.generated_minutes:
                self.generated_minutes = apply_speaker_mapping(self.generated_minutes, mapping)
                sections = parse_minutes_sections(self.generated_minutes)
                self._populate_minutes_tabs(sections)

            if self.generated_recap:
                self.generated_recap = apply_speaker_mapping(self.generated_recap, mapping)
                self._update_recap_view(self.generated_recap)

            if self.generated_actions:
                self.generated_actions = apply_speaker_mapping(self.generated_actions, mapping)
                self._update_actions_view(self.generated_actions)

            if self.active_file_hash:
                self._save_full_session(self.active_file_hash)

            close_dialog()
            messagebox.showinfo(self._t("msg.applied"), self._t("msg.speakers_applied"))

        apply_btn = ctk.CTkButton(bottom_box, text=self._t("speakers.apply"), command=apply_mapping, corner_radius=0)
        apply_btn.pack(fill="x")

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        dialog.deiconify()  # now show the fully-built speaker mapping dialog

    # -------------------------------------------------------------
    # Document Export Handler (Active Tab Only)
    # -------------------------------------------------------------
    def _export_document(self, fmt: str):
        active_tab = self.tabview.get()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = Path(self.selected_audio_file).stem if self.selected_audio_file else "Meeting"

        # Determine content, title, and filename prefix based on the active tab.
        # Titles follow the interface language; filename prefixes deliberately
        # stay fixed so saved filenames are stable across a language switch.
        if active_tab == "tab_transcript":
            content = self.processed_transcript or self.raw_transcript
            title = self._t("export.title_transcript", name=base_name)
            prefix = "Transkrip"
            include_appendix = False
        elif active_tab == "tab_recap":
            content = self.generated_recap
            title = self._t("export.title_recap", name=base_name)
            prefix = "Recap"
            include_appendix = False
        elif active_tab == "tab_actions":
            content = self.generated_actions
            title = self._t("export.title_actions", name=base_name)
            prefix = "Tindakan"
            include_appendix = False
        else:  # "tab_minutes"
            content = self.generated_minutes
            title = self._t("export.title_minutes", name=base_name)
            prefix = "Minit"
            include_appendix = True

        if not content or not content.strip():
            messagebox.showwarning(
                self._t("msg.export"),
                self._t("msg.export_nothing")
            )
            return

        exported_any = False

        if fmt in ["docx", "all"]:
            save_path = filedialog.asksaveasfilename(
                title=self._t("filepicker.save_docx"),
                initialfile=f"{prefix}_{base_name}_{timestamp}.docx",
                defaultextension=".docx",
                filetypes=[(self._t("filepicker.word_doc"), "*.docx")]
            )
            if save_path:
                try:
                    export_to_docx(
                        file_path=save_path,
                        title=title,
                        minutes_text=content,
                        raw_transcript=self.processed_transcript if include_appendix else None,
                        locale=self.ui_locale
                    )
                except DocxUnavailableError as exc:
                    messagebox.showerror(self._t("msg.error"), exc.message)
                else:
                    exported_any = True

        if fmt in ["txt", "all"]:
            save_path = filedialog.asksaveasfilename(
                title=self._t("filepicker.save_txt"),
                initialfile=f"{prefix}_{base_name}_{timestamp}.txt",
                defaultextension=".txt",
                filetypes=[(self._t("filepicker.text_file"), "*.txt")]
            )
            if save_path:
                export_to_text(
                    file_path=save_path,
                    title=title,
                    minutes_text=content,
                    transcript=self.processed_transcript if include_appendix else None,
                    locale=self.ui_locale
                )
                exported_any = True

        if exported_any:
            messagebox.showinfo(self._t("msg.export_success"), self._t("msg.export_done"))

def run_app():
    app = STTMeetApp()
    app.mainloop()

