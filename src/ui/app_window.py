"""
STTMeet GUI Application Window
Modern Desktop UI built with CustomTkinter.
Features:
- Settings: API Key configuration & verification, FFmpeg check
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
from typing import Dict, List, Optional

import customtkinter as ctk
from tkinter import filedialog, messagebox

from ..config import (
    get_api_key,
    save_api_key,
    CACHE_DIR,
    CHUNKS_DIR,
    DEFAULT_CHUNK_MINUTES
)
from ..logger import get_logger

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

class ChunkMonitorDialog(ctk.CTkToplevel):
    """
    Floating dialog panel displaying live status for each audio chunk.
    Enables users to monitor pending/working/done/error states, cancel execution,
    reprocess failed chunks individually, and extract all combined transcripts.
    """
    def __init__(self, master, chunks_meta: List[Dict], on_cancel_callback, on_reprocess_callback, on_extract_callback):
        super().__init__(master)
        self.master_app = master
        self.chunks_meta = chunks_meta
        self.on_cancel_callback = on_cancel_callback
        self.on_reprocess_callback = on_reprocess_callback
        self.on_extract_callback = on_extract_callback

        self.title("Audio Chunk Transcription Monitor")
        self.geometry("640x520")
        self.minsize(550, 400)
        self.transient(master)

        self.row_widgets: Dict[int, Dict] = {}
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header Info Card
        header_frame = ctk.CTkFrame(self, corner_radius=8)
        header_frame.grid(row=0, column=0, padx=14, pady=(12, 6), sticky="ew")
        header_frame.grid_columnconfigure(0, weight=1)

        self.summary_label = ctk.CTkLabel(
            header_frame,
            text=f"Total Chunks: {len(self.chunks_meta)} | Status: Processing...",
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
                text=f"Chunk {i + 1} ({time_str})",
                font=ctk.CTkFont(size=12, weight="bold"),
                width=200,
                anchor="w"
            )
            lbl_title.grid(row=0, column=0, padx=(10, 6), pady=8, sticky="w")

            badge = ctk.CTkLabel(
                card,
                text="Pending ⚪",
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
                text="↻ Reprocess",
                width=100,
                height=26,
                font=ctk.CTkFont(size=11),
                fg_color="#D32F2F",
                hover_color="#B71C1C",
                state="disabled",
                command=lambda c_idx=idx: self.on_reprocess_callback(c_idx)
            )
            btn_reprocess.grid(row=0, column=2, padx=(6, 10), pady=8, sticky="e")

            self.row_widgets[idx] = {
                "card": card,
                "badge": badge,
                "btn_reprocess": btn_reprocess
            }

        # Bottom Action Bar
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.grid(row=2, column=0, padx=14, pady=(6, 12), sticky="ew")
        bottom_frame.grid_columnconfigure(1, weight=1)

        self.btn_cancel = ctk.CTkButton(
            bottom_frame,
            text="⏹ Cancel",
            fg_color="#C62828",
            hover_color="#B71C1C",
            width=100,
            command=self.on_cancel_callback
        )
        self.btn_cancel.grid(row=0, column=0, padx=(0, 6), pady=6, sticky="w")

        self.btn_extract = ctk.CTkButton(
            bottom_frame,
            text="📥 Extract Transcript",
            fg_color="#2E7D32",
            hover_color="#1B5E20",
            font=ctk.CTkFont(weight="bold"),
            width=170,
            state="disabled",
            command=self.on_extract_callback
        )
        self.btn_extract.grid(row=0, column=2, padx=6, pady=6, sticky="e")

        self.btn_close = ctk.CTkButton(
            bottom_frame,
            text="Hide Window",
            width=100,
            command=self.withdraw
        )
        self.btn_close.grid(row=0, column=3, padx=(6, 0), pady=6, sticky="e")

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

        states_config = {
            "pending": ("Pending ⚪", "gray", ("#E0E0E0", "#2B2B2B"), "disabled"),
            "working": ("Transcribing... 🔵", "#1976D2", ("#BBDEFB", "#0D47A1"), "disabled"),
            "done": ("Completed 🟢", "#2E7D32", ("#C8E6C9", "#1B5E20"), "disabled"),
            "error": (f"Error: {detail[:25]}... 🔴" if detail else "Error 🔴", "#C62828", ("#FFCDD2", "#B71C1C"), "normal"),
            "cancelled": ("Cancelled ⚪", "gray", ("#E0E0E0", "#2B2B2B"), "normal")
        }

        text, fg_col, bg_col, btn_state = states_config.get(state, states_config["pending"])
        badge.configure(text=text, text_color=fg_col, fg_color=bg_col)
        btn_reprocess.configure(state=btn_state)

    def update_overall_summary(self, completed_count: int, total_count: int, has_errors: bool = False):
        pct = (completed_count / total_count) if total_count > 0 else 0.0
        self.progress_bar.set(pct)

        status_text = f"Total Chunks: {total_count} | Completed: {completed_count}/{total_count}"
        if completed_count == total_count:
            status_text += " | All Chunks Done! Click 'Extract Transcript'"
            self.btn_extract.configure(state="normal")
            self.btn_cancel.configure(state="disabled")
        elif has_errors:
            status_text += " | Some chunks failed. Click '↻ Reprocess' on red items."
            self.btn_extract.configure(state="disabled")
        else:
            self.btn_extract.configure(state="disabled")

        self.summary_label.configure(text=status_text)


class STTMeetApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"STTMeet {get_display_version()} — Malaysian Meeting STT & Minutes Generator")
        self.geometry("1100x820")
        self.minsize(950, 750)

        # Worker & State
        self.worker_thread: Optional[threading.Thread] = None
        self.cancel_event = threading.Event()
        self.is_processing = False

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

        self._build_ui()
        self._check_initial_environment()
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)

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

    def _build_header_and_settings(self):
        top_frame = ctk.CTkFrame(self, corner_radius=10)
        top_frame.grid(row=0, column=0, padx=16, pady=(12, 6), sticky="ew")
        top_frame.grid_columnconfigure(1, weight=1)

        title_label = ctk.CTkLabel(
            top_frame,
            text="🎙️ STTMeet",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        title_label.grid(row=0, column=0, padx=(16, 10), pady=10, sticky="w")

        # API Key input
        key_label = ctk.CTkLabel(top_frame, text="Gemini API Key:", font=ctk.CTkFont(size=12))
        key_label.grid(row=0, column=1, padx=(10, 4), pady=10, sticky="e")

        self.api_key_entry = ctk.CTkEntry(
            top_frame,
            width=260,
            show="•",
            placeholder_text="Enter GEMINI_API_KEY..."
        )
        self.api_key_entry.grid(row=0, column=2, padx=4, pady=10)
        
        saved_key = get_api_key()
        if saved_key:
            self.api_key_entry.insert(0, saved_key)

        save_btn = ctk.CTkButton(top_frame, text="Save Key", width=75, command=self._save_api_key)
        save_btn.grid(row=0, column=3, padx=4, pady=10)

        # Status Badges
        self.ffmpeg_badge = ctk.CTkLabel(
            top_frame,
            text="FFmpeg: Checking...",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.ffmpeg_badge.grid(row=0, column=4, padx=(10, 16), pady=10)

    def _build_file_section(self):
        file_frame = ctk.CTkFrame(self, corner_radius=10)
        file_frame.grid(row=1, column=0, padx=16, pady=6, sticky="ew")
        file_frame.grid_columnconfigure(1, weight=1)

        browse_btn = ctk.CTkButton(
            file_frame,
            text="📂 Select Audio File",
            command=self._browse_audio_file,
            width=160,
            font=ctk.CTkFont(weight="bold")
        )
        browse_btn.grid(row=0, column=0, padx=16, pady=12, sticky="w")

        self.file_label = ctk.CTkLabel(
            file_frame,
            text="No audio file selected (Supports .mp3, .m4a, .wav, .aac, .flac, .mp4)",
            anchor="w",
            font=ctk.CTkFont(size=13)
        )
        self.file_label.grid(row=0, column=1, padx=10, pady=12, sticky="ew")

        # Audio Info Row
        self.audio_stats_label = ctk.CTkLabel(
            file_frame,
            text="Duration: --:--:--  |  File Size: -- MB  |  Estimated Cost: $0.00",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.audio_stats_label.grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 10), sticky="w")

    def _build_controls_section(self):
        ctrl_frame = ctk.CTkFrame(self, corner_radius=10)
        ctrl_frame.grid(row=2, column=0, padx=16, pady=6, sticky="ew")
        ctrl_frame.grid_columnconfigure(4, weight=1)

        # Engine Selector
        engine_lbl = ctk.CTkLabel(ctrl_frame, text="Engine:")
        engine_lbl.grid(row=0, column=0, padx=(16, 6), pady=10, sticky="w")

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

        # Language Selector
        lang_lbl = ctk.CTkLabel(ctrl_frame, text="Minutes Lang:")
        lang_lbl.grid(row=0, column=2, padx=(16, 6), pady=10, sticky="w")

        self.lang_var = ctk.StringVar(value="Bahasa Melayu")
        self.lang_dropdown = ctk.CTkOptionMenu(
            ctrl_frame,
            values=["Bahasa Melayu", "English", "Bilingual"],
            variable=self.lang_var,
            width=130
        )
        self.lang_dropdown.grid(row=0, column=3, padx=6, pady=10, sticky="w")

        # Chunk Size Selector
        chunk_lbl = ctk.CTkLabel(ctrl_frame, text="Chunk:")
        chunk_lbl.grid(row=0, column=4, padx=(16, 6), pady=10, sticky="w")

        self.chunk_size_var = ctk.StringVar(value="25 min")
        self.chunk_dropdown = ctk.CTkOptionMenu(
            ctrl_frame,
            values=["15 min", "20 min", "25 min", "30 min", "45 min"],
            variable=self.chunk_size_var,
            width=90
        )
        self.chunk_dropdown.grid(row=0, column=5, padx=6, pady=10, sticky="w")

        # Pre-process checkbox
        self.preprocess_var = ctk.BooleanVar(value=True)
        self.preprocess_chk = ctk.CTkCheckBox(
            ctrl_frame,
            text="Pre-process (16kHz Mono)",
            variable=self.preprocess_var
        )
        self.preprocess_chk.grid(row=0, column=6, padx=16, pady=10, sticky="w")

        # Action Buttons
        self.start_btn = ctk.CTkButton(
            ctrl_frame,
            text="▶ Transcribe Audio",
            fg_color="#2E7D32",
            hover_color="#1B5E20",
            font=ctk.CTkFont(weight="bold"),
            command=self._start_processing_pipeline,
            width=150
        )
        self.start_btn.grid(row=0, column=7, padx=4, pady=10, sticky="e")

        self.gen_minutes_btn = ctk.CTkButton(
            ctrl_frame,
            text="📝 Generate Minutes",
            fg_color="#1976D2",
            hover_color="#1565C0",
            font=ctk.CTkFont(weight="bold"),
            command=self._start_minutes_generation_only,
            state="disabled",
            width=150
        )
        self.gen_minutes_btn.grid(row=0, column=8, padx=4, pady=10, sticky="e")

        self.cancel_btn = ctk.CTkButton(
            ctrl_frame,
            text="⏹ Cancel",
            fg_color="#C62828",
            hover_color="#B71C1C",
            command=self._cancel_processing,
            state="disabled",
            width=75
        )
        self.cancel_btn.grid(row=0, column=9, padx=4, pady=10, sticky="e")

        self.monitor_btn = ctk.CTkButton(
            ctrl_frame,
            text="📊 Monitor Chunks",
            fg_color=("#455A64", "#37474F"),
            hover_color=("#37474F", "#263238"),
            font=ctk.CTkFont(weight="bold"),
            command=self._open_or_focus_chunk_monitor,
            state="disabled",
            width=130
        )
        self.monitor_btn.grid(row=0, column=10, padx=4, pady=10, sticky="e")

        self.reset_btn = ctk.CTkButton(
            ctrl_frame,
            text="🔄 Reset",
            fg_color=("#78909C", "#455A64"),
            hover_color=("#546E7A", "#37474F"),
            font=ctk.CTkFont(weight="bold"),
            command=self._reset_workspace,
            width=85
        )
        self.reset_btn.grid(row=0, column=11, padx=4, pady=10, sticky="e")

        self.save_session_btn = ctk.CTkButton(
            ctrl_frame,
            text="💾 Save Session",
            fg_color=("#00897B", "#00695C"),
            hover_color=("#00796B", "#004D40"),
            font=ctk.CTkFont(weight="bold"),
            command=self._save_session_manually,
            state="disabled",
            width=130
        )
        self.save_session_btn.grid(row=0, column=12, padx=(4, 16), pady=10, sticky="e")

        # Visual Stepper Bar
        self.stepper_frame = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        self.stepper_frame.grid(row=1, column=0, columnspan=13, padx=16, pady=(4, 4), sticky="ew")
        for col_idx in range(7):
            self.stepper_frame.grid_columnconfigure(col_idx, weight=1 if col_idx % 2 == 0 else 0)

        self.step_badges = {}
        steps_def = [
            ("step1", "① Preprocess"),
            ("step2", "② Chunking"),
            ("step3", "③ Transcribe"),
            ("step4", "④ Minutes & Actions")
        ]

        for s_idx, (s_key, s_label) in enumerate(steps_def):
            grid_col = s_idx * 2
            badge = ctk.CTkLabel(
                self.stepper_frame,
                text=f"{s_label} ⚪",
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
        self.progress_bar.grid(row=2, column=0, columnspan=13, padx=16, pady=(4, 4), sticky="ew")
        self.progress_bar.set(0.0)

        self.status_label = ctk.CTkLabel(
            ctrl_frame,
            text="Ready. Select an audio file and click Transcribe Audio.",
            font=ctk.CTkFont(size=12),
            anchor="w"
        )
        self.status_label.grid(row=3, column=0, columnspan=13, padx=16, pady=(0, 10), sticky="w")

    def _build_tabs_section(self):
        self.tabview = ctk.CTkTabview(self, corner_radius=10)
        self.tabview.grid(row=3, column=0, padx=16, pady=6, sticky="nsew")

        self.tab_transcript = self.tabview.add("Transkrip Penuh / Transcript")
        self.tab_minutes = self.tabview.add("Minit Mesyuarat / Minutes")
        self.tab_summary = self.tabview.add("Ringkasan / Summary")
        self.tab_actions = self.tabview.add("Senarai Tindakan / Action Items")

        # Setup textboxes in each tab
        self.txt_transcript = self._create_textbox(self.tab_transcript)

        # Minutes tab with top inline retry banner
        self.tab_minutes.grid_columnconfigure(0, weight=1)
        self.tab_minutes.grid_rowconfigure(1, weight=1)

        self.minutes_banner_frame = ctk.CTkFrame(self.tab_minutes, fg_color=("#FFEBEE", "#421C1C"), corner_radius=6)
        self.minutes_banner_label = ctk.CTkLabel(
            self.minutes_banner_frame,
            text="⚠️ Server spike encountered. Your transcript is safe.",
            text_color=("#C62828", "#FFCDD2"),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.minutes_banner_label.pack(side="left", padx=12, pady=6)

        self.retry_minutes_btn = ctk.CTkButton(
            self.minutes_banner_frame,
            text="↻ Retry Generation",
            fg_color="#D32F2F",
            hover_color="#B71C1C",
            width=140,
            command=self._start_minutes_generation_only
        )
        self.retry_minutes_btn.pack(side="right", padx=12, pady=6)
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
            text="👥 Map Speaker Names",
            command=self._open_speaker_mapping_dialog,
            width=160
        )
        speaker_btn.grid(row=0, column=0, padx=16, pady=10, sticky="w")

        # Export Buttons
        export_docx_btn = ctk.CTkButton(
            bottom_frame,
            text="📄 Export Word (.docx)",
            command=lambda: self._export_document("docx"),
            width=150
        )
        export_docx_btn.grid(row=0, column=2, padx=4, pady=10)

        export_md_btn = ctk.CTkButton(
            bottom_frame,
            text="📝 Export Markdown (.md)",
            command=lambda: self._export_document("md"),
            width=150
        )
        export_md_btn.grid(row=0, column=3, padx=4, pady=10)

        export_txt_btn = ctk.CTkButton(
            bottom_frame,
            text="📃 Export Text (.txt)",
            command=lambda: self._export_document("txt"),
            width=130
        )
        export_txt_btn.grid(row=0, column=4, padx=4, pady=10)

        export_all_btn = ctk.CTkButton(
            bottom_frame,
            text="📦 Export All",
            fg_color="#1565C0",
            hover_color="#0D47A1",
            command=lambda: self._export_document("all"),
            width=110
        )
        export_all_btn.grid(row=0, column=5, padx=(4, 16), pady=10)

    # -------------------------------------------------------------
    # Helpers & Validation
    # -------------------------------------------------------------
    def _check_initial_environment(self):
        is_ok, msg = check_ffmpeg()
        if is_ok:
            self.ffmpeg_badge.configure(text="FFmpeg: ✅ Installed", text_color="#2E7D32")
        else:
            self.ffmpeg_badge.configure(text="FFmpeg: ❌ Not Found in PATH", text_color="#C62828")
            messagebox.showwarning(
                "FFmpeg Warning",
                "FFmpeg was not detected in your system PATH.\nPlease ensure FFmpeg is installed to support all audio formats."
            )

    def _save_api_key(self):
        new_key = self.api_key_entry.get().strip()
        if not new_key:
            messagebox.showwarning("Warning", "Please enter a valid Gemini API Key.")
            return
        save_api_key(new_key)
        messagebox.showinfo("Success", "Gemini API Key saved successfully to .env.")

    def _browse_audio_file(self):
        filetypes = [
            ("Supported Audio Files", "*.mp3 *.m4a *.wav *.aac *.ogg *.flac *.mp4"),
            ("All Files", "*.*")
        ]
        chosen = filedialog.askopenfilename(title="Select Meeting Audio", filetypes=filetypes)
        if not chosen:
            return

        self.selected_audio_file = chosen
        file_name = Path(chosen).name
        file_size_mb = os.path.getsize(chosen) / (1024 * 1024)

        try:
            self.audio_duration_seconds = get_audio_duration(chosen)
            cost_info = estimate_cost_and_tokens(self.audio_duration_seconds)
            
            self.file_label.configure(text=f"Selected: {file_name}")
            self.audio_stats_label.configure(
                text=f"Duration: {cost_info['formatted_duration']}  |  "
                     f"File Size: {file_size_mb:.1f} MB  |  "
                     f"Est. Tokens: ~{cost_info['estimated_input_tokens']:,}  |  "
                     f"Est. Cost: ~${cost_info['estimated_cost_usd']:.2f}"
            )
        except Exception as e:
            self.file_label.configure(text=f"Selected: {file_name}")
            self.audio_stats_label.configure(text=f"Could not calculate audio duration: {e}")

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
            self._set_status("Smart Cloud Mode: Auto-fails over between Gemini 3, 3.8, and 3.5 if free quotas fill up.")
        else:
            self._set_status(f"Cloud mode selected: Uses {choice.strip()} with automatic quota failover protection.")

    # -------------------------------------------------------------
    # Processing Pipeline (Threaded)
    # -------------------------------------------------------------
    def _start_processing_pipeline(self):
        if not self.selected_audio_file or not os.path.exists(self.selected_audio_file):
            messagebox.showerror("Error", "Please select a valid meeting audio file first.")
            return

        api_key = self.api_key_entry.get().strip()
        if not api_key:
            messagebox.showerror("Error", "Gemini API Key is required. Please enter and save your key.")
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
        if messagebox.askyesno("Cancel", "Are you sure you want to cancel the ongoing transcription?"):
            self.cancel_event.set()
            self._set_status("Cancelling... finishing active operation.")

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
            on_extract_callback=self._extract_transcript_from_monitor
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
                self._set_status("[Step 1/4] Pre-processing audio (16kHz mono MP3)...")
                target_audio = preprocess_audio(
                    audio_path,
                    progress_callback=lambda msg: self._set_status(f"[Step 1/4] {msg}")
                )
                self._update_step_badge("step1", "done")
            else:
                self._set_status("[Step 1/4] Audio preprocessing skipped.")
                self._update_step_badge("step1", "done", "(skipped)")

            if self.cancel_event.is_set():
                self._on_pipeline_cancelled()
                return

            # Step 2: Slicing into Chunks
            self._update_step_badge("step2", "working")
            self._set_status("[Step 2/4] Preparing audio chunks (checking cache)...")
            chunks = split_audio_into_chunks(
                target_audio,
                chunk_minutes=chunk_minutes,
                progress_callback=lambda msg, pct: self._set_progress(pct * 0.2, f"[Step 2/4] {msg}")
            )
            total_chunks = len(chunks)
            self.active_chunks_meta = chunks
            self._update_step_badge("step2", "done", f"({total_chunks} chunks)")

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
                    self._set_progress(base_pct, f"[Step 3/4] Loaded {chunk_display} from cache.")
                    continue

                # Mark chunk as working in monitor & main status
                self._update_chunk_monitor_item(idx, "working")
                engine_display_name = model_override or "Gemini Auto-Failover"
                self._set_progress(base_pct, f"[Step 3/4] Transcribing {chunk_display} ({engine_display_name})...")
                self._update_step_badge("step3", "working", f"({i+1}/{total_chunks})")

                try:
                    if not client:
                        raise ValueError("Gemini API Client is required.")
                    raw_chunk_text = transcribe_audio_chunk(
                        client=client,
                        chunk_file_path=chunk_info["file_path"],
                        previous_tail_transcript=previous_tail_context,
                        progress_callback=lambda msg: self._set_status(f"[Step 3/4] {chunk_display}: {msg}"),
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
                self._set_progress(0.80, "All chunks completed! Click 'Extract Transcript' in the Monitor window.")
            else:
                self._update_step_badge("step3", "error", f"({completed_count}/{total_chunks} done)")
                self._set_progress(0.80, f"Batch finished: {completed_count}/{total_chunks} chunks completed. Please click '↻ Reprocess' on failed chunks.")

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
            messagebox.showerror("Error", f"Chunk metadata for index {chunk_index} not found.")
            return

        api_key = self.api_key_entry.get().strip()
        if not api_key:
            messagebox.showerror("Error", "Gemini API key is required.")
            return

        self._update_chunk_monitor_item(chunk_index, "working")
        self._set_status(f"Reprocessing Chunk {chunk_index + 1}...")

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
                self._set_status(f"Chunk {chunk_index + 1} reprocessed successfully!")
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
                self._set_status(f"Reprocess of Chunk {chunk_index + 1} failed: {err_str[:40]}")

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _extract_transcript_from_monitor(self):
        """Combines all green chunk transcripts in proper sequence and populates the main app."""
        total = len(self.active_chunks_meta)
        missing = [c["chunk_index"] for c in self.active_chunks_meta if self.active_chunk_status.get(c["chunk_index"], {}).get("status") != "done"]

        if missing:
            msg = f"Chunks {[m + 1 for m in missing]} are not completed yet.\nExtract available completed chunks anyway?"
            if not messagebox.askyesno("Partial Extraction", msg):
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

        self._set_progress(1.0, f"Extracted transcript ({len(ordered_parts)} chunks). Ready to generate minutes!")
        messagebox.showinfo("Extraction Complete", f"Successfully extracted {len(ordered_parts)} chunk(s) into the Transcript tab!\nYou can now click '📝 Generate Minutes'.")

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
        self._set_progress(0.85, f"[Step 4/4] Generating Meeting Minutes & Action Items ({language})...")

        try:
            if not client:
                api_key = self.api_key_entry.get().strip()
                if not api_key:
                    raise ValueError("Gemini API key is required to synthesize minutes and action items.")
                client = get_gemini_client(api_key)

            transcript_to_use = self.processed_transcript or self.raw_transcript
            if not transcript_to_use.strip():
                raise ValueError("Transcript is empty. Cannot generate minutes.")

            self.generated_minutes = generate_meeting_minutes(
                client=client,
                full_transcript=transcript_to_use,
                language=language,
                progress_callback=lambda msg: self._set_status(f"[Step 4/4] {msg}"),
                model_override=self._get_selected_model_override()
            )

            sections = parse_minutes_sections(self.generated_minutes)
            self.after(0, lambda secs=sections: self._populate_minutes_tabs(secs))
            self.after(0, self._hide_minutes_error_banner)
            self._update_step_badge("step4", "done")
            self._save_full_session(file_hash)
            self._set_progress(1.0, "Ready. Transcription and meeting minutes completed successfully!")
            self.after(0, self._on_pipeline_finished)

        except Exception as err:
            err_msg = str(err)
            log.warning("Minutes synthesis failed (transcript remains protected): %s", err_msg)
            self._update_step_badge("step4", "error", "(Failed)")
            self.after(0, lambda msg=err_msg: self._show_minutes_error_banner(msg))
            self._set_progress(0.80, "Transcript completed. Minutes generation failed (click Retry).")
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
            messagebox.showwarning("Notice", "No transcript available. Please transcribe audio first.")
            return

        api_key = self.api_key_entry.get().strip()
        if not api_key:
            messagebox.showerror("Error", "Gemini API key is required for minutes synthesis.")
            return

        if self.is_processing:
            messagebox.showinfo("Busy", "A task is already running. Please wait for it to complete.")
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
        base_name = badge.cget("text").split()[0]
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
            messagebox.showwarning("Save Session", "Please select a valid audio file first.")
            return

        if self.is_processing:
            if not messagebox.askyesno(
                "Save Session",
                "A task is currently running. Save the session in its current state anyway?"
            ):
                return

        audio_hash = compute_file_hash(self.selected_audio_file)
        if self._save_full_session(audio_hash):
            messagebox.showinfo("Session Saved", f"Session saved for:\n{Path(self.selected_audio_file).name}")
        else:
            messagebox.showerror("Save Session", "Could not write the session file. Check sttmeet.log for details.")

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
                message = f"Restored session for {Path(audio_path).name} ({chunk_summary})."
            else:
                message = "Restored previous session from cache!"
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
        self.lang_var.set(clean["language"])
        self.chunk_size_var.set(f"{clean['chunk_minutes']} min")
        self.preprocess_var.set(clean["preprocess"])
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
        return f"{done}/{len(chunks)} chunks done"

    def _reset_workspace(self):
        """
        Unconditionally clears all transcripts, minutes, monitors, and purges all
        cached progress, chunks, manifests, and session checkpoints so the next run is 100% fresh.
        """
        if self.is_processing:
            messagebox.showwarning("Notice", "Cannot reset while a transcription task is currently running.")
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

        self._set_status("Workspace reset & cache completely cleared. Ready for fresh transcription.")

    def _show_minutes_error_banner(self, err_msg: str):
        self.minutes_banner_label.configure(text=f"⚠️ Minutes failed ({err_msg[:60]}...). Transcript is safe.")
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
        self.txt_summary.insert("1.0", sections.get("summary", "Summary not generated."))

        self.txt_actions.delete("1.0", "end")
        self.txt_actions.insert("1.0", sections.get("action_items", "No action items extracted."))

    def _on_pipeline_finished(self):
        self.is_processing = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        messagebox.showinfo(
            "Completed",
            "Meeting transcription, minutes, and action items have been generated!\n"
            "You can now review the tabs or map speaker names before exporting."
        )

    def _on_pipeline_cancelled(self):
        self.is_processing = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self._set_status("Operation cancelled by user. Partial progress saved in cache.")
        if self.active_file_hash:
            self._save_full_session(self.active_file_hash)

    def _on_pipeline_error(self, error_message: str):
        self.is_processing = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self._set_status(f"Error: {error_message}")
        messagebox.showerror("Transcription Error", f"An error occurred:\n{error_message}")

    # -------------------------------------------------------------
    # Speaker Mapping Dialog
    # -------------------------------------------------------------
    def _open_speaker_mapping_dialog(self):
        if not self.raw_transcript:
            messagebox.showinfo("Speaker Mapping", "Please transcribe an audio file first to detect speakers.")
            return

        speakers = self.detected_speakers or extract_speakers(self.raw_transcript)
        if not speakers:
            messagebox.showinfo("Speaker Mapping", "No speakers were detected in the transcript.")
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Map Speaker Names")
        dialog.geometry("450x380")
        dialog.transient(self)
        dialog.grab_set()

        lbl = ctk.CTkLabel(
            dialog,
            text="Assign real names to detected voice tags:",
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

            name_entry = ctk.CTkEntry(row_frame, placeholder_text=f"e.g. En. Ahmad / Sarah")
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
            messagebox.showinfo("Applied", "Speaker names updated across transcript and minutes!")

        apply_btn = ctk.CTkButton(dialog, text="Apply Speaker Names", command=apply_mapping)
        apply_btn.pack(padx=16, pady=12)

    # -------------------------------------------------------------
    # Document Export Handler
    # -------------------------------------------------------------
    def _export_document(self, fmt: str):
        if not self.processed_transcript and not self.generated_minutes:
            messagebox.showwarning("Export", "No transcribed content or minutes available to export.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = Path(self.selected_audio_file).stem if self.selected_audio_file else "Meeting"

        title = f"Minit Mesyuarat - {base_name}"
        minutes_content = self.generated_minutes or self.processed_transcript
        transcript_content = self.processed_transcript

        if fmt in ["docx", "all"]:
            save_path = filedialog.asksaveasfilename(
                title="Save Word Document",
                initialfile=f"Minit_{base_name}_{timestamp}.docx",
                defaultextension=".docx",
                filetypes=[("Word Document", "*.docx")]
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
                title="Save Markdown Document",
                initialfile=f"Minit_{base_name}_{timestamp}.md",
                defaultextension=".md",
                filetypes=[("Markdown Document", "*.md")]
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
                title="Save Plain Text Document",
                initialfile=f"Minit_{base_name}_{timestamp}.txt",
                defaultextension=".txt",
                filetypes=[("Text File", "*.txt")]
            )
            if save_path:
                export_to_text(
                    file_path=save_path,
                    title=title,
                    minutes_text=minutes_content,
                    transcript=transcript_content
                )

        messagebox.showinfo("Export Successful", f"Document(s) saved successfully!")

def run_app():
    app = STTMeetApp()
    app.mainloop()
