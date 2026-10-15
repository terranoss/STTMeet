"""
STTMeet Localization
UI chrome translations for English (en) and Bahasa Melayu (ms).

This module is pure data + string logic with no Tk dependency, so it is fully
unit-testable. It translates the *interface only*: button labels, tab names,
dialog text, status messages and message boxes.

Two things are deliberately NOT translated here:

1. Generated minutes / summary / action items. Those are written by Gemini using
   MINUTES_SYNTHESIS_PROMPTS in minutes_generator.py and are selected by the
   minutes-language cascade (see MINUTES_LANG_BY_UI_LOCALE below).
2. Logic-coupled literals such as the engine option labels, the minutes-language
   values, and the "N min" chunk values. Those are parsed as data or used as
   lookup keys; translating them breaks model routing and session validation.
   See LOGIC_COUPLED_LITERALS, which test_pipeline.py asserts against this table.
"""

from datetime import datetime
from typing import Any, Dict, Optional

# The UI offers exactly one interface language at a time, defaulting to Bahasa
# Melayu. A combined "Malay / English" mode used to exist here; it was removed
# because interleaved bilingual output degraded the generated minutes and made
# the exported documents read as mixed-language.
LOCALES = ("en", "ms")
ALL_MODES = LOCALES
DEFAULT_LOCALE = "en"

# Names of the two language modes. These label the toggle buttons themselves,
# so they are intentionally not localized: "Bahasa Melayu" is the same word in
# both languages, and translating them would produce "Bahasa Melayu / Bahasa
# Melayu" nonsense.
MODE_NAMES = {
    "en": "English",
    "ms": "Bahasa Melayu",
}

# UI locale -> minutes language value stored in lang_var.
# lang_var's values are validated by session_store.VALID_LANGUAGES and are used
# as dict keys to pick a Gemini prompt, so these are canonical and untranslated.
MINUTES_LANG_BY_UI_LOCALE = {
    "en": "English",
    "ms": "Bahasa Melayu",
}

# Display-only names for the read-only output-language chip. Never written back
# to lang_var. test_pipeline.py asserts the keys match VALID_LANGUAGES exactly.
MINUTES_LANG_DISPLAY = {
    "Bahasa Melayu": {"en": "Bahasa Melayu", "ms": "Bahasa Melayu"},
    "English": {"en": "English", "ms": "Inggeris"},
}

# strftime("%B") always emits English month names regardless of the process
# locale, so the exporter formats the date itself using this table.
MONTH_NAMES_MS = (
    "Januari", "Februari", "Mac", "April", "Mei", "Jun",
    "Julai", "Ogos", "September", "Oktober", "November", "Disember",
)

TEMPLATE_DISPLAY = {
    "action_minutes": {
        "en": "Action Minutes",
        "ms": "Minit Tindakan",
    },
    "discussion_minutes": {
        "en": "Discussion (Topical)",
        "ms": "Perbincangan (Topikal)",
    },
    "three_column": {
        "en": "Three-Column",
        "ms": "Tiga Lajur",
    },
    "board_governance": {
        "en": "Board / Governance",
        "ms": "Lembaga Pengarah / Tadbir Urus",
    },
}

# Values that are parsed as data or used as lookup keys. These must never be
# routed through translate(); test_pipeline.py fails if any appears in STRINGS.
# Note: the literal "GEMINI_API_KEY" is deliberately absent. It is a documented
# environment variable name, safe to show in the Settings placeholder, and is
# never parsed as UI data.
LOGIC_COUPLED_LITERALS = {
    "⚡ Gemini Cloud (Auto-Failover)",
    "☁️ Gemini 3 Flash",
    "☁️ Gemini 3.8 Flash",
    "☁️ Gemini 3.5 Flash",
    "☁️ Gemini 3.5 Flash Lite",
    "Bahasa Melayu",
    "English",
    "15 min",
    "20 min",
    "25 min",
    "30 min",
    "45 min",
}

STRINGS: Dict[str, Dict[str, str]] = {
    # --- Window -------------------------------------------------------
    "window.title": {
        "en": "STTMeet {version} — Malaysian Meeting STT & Minutes Generator",
        "ms": "STTMeet {version} — Penjana Transkrip & Minit Mesyuarat Malaysia",
    },
    "monitor.title": {"en": "Audio Chunk Transcription Monitor", "ms": "Pemantau Transkrip Audio"},

    # --- Header -------------------------------------------------------
    "header.title": {"en": "🎙️ STTMeet", "ms": "🎙️ STTMeet"},
    "ffmpeg.checking": {"en": "FFmpeg: Checking...", "ms": "FFmpeg: Menyemak..."},
    "ffmpeg.installed": {"en": "FFmpeg: ✅ Installed", "ms": "FFmpeg: ✅ Dipasang"},
    "ffmpeg.missing": {"en": "FFmpeg: ❌ Not Found in PATH", "ms": "FFmpeg: ❌ Tidak Dijumpai dalam PATH"},

    # --- Drawer menu --------------------------------------------------
    "menu.section_general": {"en": "GENERAL", "ms": "UTAMA"},
    "menu.section_tools": {"en": "TOOLS & ABOUT", "ms": "ALAT & TENTANG"},
    "menu.language_label": {"en": "🌐  Language / Bahasa", "ms": "🌐  Bahasa / Language"},
    "menu.settings": {"en": "Settings", "ms": "Tetapan"},
    "menu.save_session": {"en": "Save Session", "ms": "Simpan Sesi"},
    "menu.open_log_folder": {"en": "Open Log Folder", "ms": "Buka Folder Log"},
    "menu.docs": {"en": "Documentation", "ms": "Dokumentasi"},
    "menu.about": {"en": "About", "ms": "Tentang"},
    "menu.close_hint": {
        "en": "Press Esc or click outside to close",
        "ms": "Tekan Esc atau klik di luar untuk tutup",
    },
    "menu.key_configured": {
        "en": "✅  API Key configured",
        "ms": "✅  Kunci API dikonfigurasi",
    },
    "menu.key_missing": {
        "en": "⚠️  No API Key — open Settings",
        "ms": "⚠️  Tiada Kunci API — buka Tetapan",
    },

    # --- File section -------------------------------------------------
    "file.no_selection": {
        "en": "No audio file selected (Supports .mp3, .m4a, .wav, .aac, .flac, .mp4)",
        "ms": "Tiada fail audio dipilih (Menyokong .mp3, .m4a, .wav, .aac, .flac, .mp4)",
    },
    "file.select": {"en": "📂 Select Audio File", "ms": "📂 Pilih Fail Audio"},
    "file.selected": {"en": "Selected: {name}", "ms": "Dipilih: {name}"},
    "file.stats": {
        "en": "Duration: {duration}  |  File Size: {size} MB  |  Est. Tokens: ~{tokens}  |  Est. Cost: ~${cost}",
        "ms": "Tempoh: {duration}  |  Saiz Fail: {size} MB  | Angg. Token: ~{tokens}  |  Angg. Kos: ~${cost}",
    },
    "file.stats_placeholder": {
        "en": "Duration: --:--:--  |  File Size: -- MB  |  Estimated Cost: $0.00",
        "ms": "Tempoh: --:--:--  |  Saiz Fail: -- MB  |  Anggaran Kos: $0.00",
    },
    "file.stats_error": {
        "en": "Could not calculate audio duration: {error}",
        "ms": "Tidak dapat mengira tempoh audio: {error}",
    },
    "filepicker.audio_title": {"en": "Select Meeting Audio", "ms": "Pilih Audio Mesyuarat"},
    "filepicker.supported": {"en": "Supported Audio Files", "ms": "Fail Audio Disokong"},
    "filepicker.all": {"en": "All Files", "ms": "Semua Fail"},
    "filepicker.save_docx": {"en": "Save Word Document", "ms": "Simpan Dokumen Word"},
    "filepicker.save_md": {"en": "Save Markdown Document", "ms": "Simpan Dokumen Markdown"},
    "filepicker.save_txt": {"en": "Save Plain Text Document", "ms": "Simpan Dokumen Teks Biasa"},
    "filepicker.word_doc": {"en": "Word Document", "ms": "Dokumen Word"},
    "filepicker.markdown_doc": {"en": "Markdown Document", "ms": "Dokumen Markdown"},
    "filepicker.text_file": {"en": "Text File", "ms": "Fail Teks"},

    # --- Controls row -------------------------------------------------
    "control.template": {"en": "Meeting Minute Format:", "ms": "Format Minit Mesyuarat:"},
    "control.preprocess": {"en": "Pre-process (16kHz Mono)", "ms": "Praproses (16kHz Mono)"},
    "control.output_lang": {"en": "🌐 Output: {value}", "ms": "🌐 Keluaran: {value}"},
    "btn.transcribe": {"en": "▶ Start", "ms": "▶ Mula"},
    "btn.generate_minutes": {"en": "📝 Generate Minutes", "ms": "📝 Jana Minit"},
    "btn.generate_recap": {"en": "📋 Generate Recap", "ms": "📋 Jana Rekap"},
    "btn.generate_actions": {"en": "📋 Generate Action Items", "ms": "📋 Jana Senarai Tindakan"},
    "btn.cancel": {"en": "⏹ Cancel", "ms": "⏹ Batal"},
    "btn.monitor": {"en": "📊 Monitor Chunks", "ms": "📊 Pantau Potongan"},
    "btn.reset": {"en": "🔄 Reset", "ms": "🔄 Set Semula"},
    "btn.save_session": {"en": "💾 Save Session", "ms": "💾 Simpan Sesi"},
    "btn.retry_minutes": {"en": "↻ Retry Generation", "ms": "↻ Cuba Jana Semula"},
    "btn.retry_recap": {"en": "↻ Retry Recap", "ms": "↻ Cuba Semula Rekap"},
    "btn.retry_actions": {"en": "↻ Retry Action Items", "ms": "↻ Cuba Semula Tindakan"},
    "btn.view_preview": {"en": "👁 Preview", "ms": "👁 Pratonton"},
    "btn.view_raw": {"en": "📝 Markdown", "ms": "📝 Teks Asal"},
    "btn.map_speakers": {"en": "👥 Map Speaker Names", "ms": "👥 Petakan Nama Penceramah"},
    "btn.export_docx": {"en": "📄 Export Word (.docx)", "ms": "📄 Eksport Word (.docx)"},
    "btn.export_md": {"en": "📝 Export Markdown (.md)", "ms": "📝 Eksport Markdown (.md)"},
    "btn.export_txt": {"en": "📃 Export Text (.txt)", "ms": "📃 Eksport Teks (.txt)"},
    "btn.export_all": {"en": "📦 Export All", "ms": "📦 Eksport Semua"},

    # --- Stepper ------------------------------------------------------
    "step.step1": {"en": "① Preprocess", "ms": "① Praproses"},
    "step.step2": {"en": "② Chunking", "ms": "② Pemotongan"},
    "step.step3": {"en": "③ Transcribe", "ms": "③ Transkrip"},
    "step.step4": {"en": "④ Minutes & Actions", "ms": "④ Minit & Tindakan"},
    "step.skipped": {"en": "(skipped)", "ms": "(dilangkau)"},
    "step.failed": {"en": "(failed)", "ms": "(gagal)"},
    "step.chunk_count": {"en": "({count} chunks)", "ms": "({count} potongan)"},

    # --- Tabs ----------------------------------------------------------
    "tab.transcript": {
        "en": "Transcript", "ms": "Transkrip Penuh",
    },
    "tab.minutes": {
        "en": "Minutes", "ms": "Minit Mesyuarat",
    },
    "tab.recap": {
        "en": "Meeting Recap", "ms": "Rekap Mesyuarat",
    },
    "tab.actions": {
        "en": "Action Items", "ms": "Senarai Tindakan",
    },

    # --- Status bar ---------------------------------------------------
    "status.ready": {
        "en": "Ready. Select an audio file and click Start.",
        "ms": "Sedia. Pilih fail audio dan klik Mula.",
    },
    "status.log_opened": {"en": "Opened log folder: {folder}", "ms": "Folder log dibuka: {folder}"},
    "status.key_saved": {"en": "Gemini API Key saved successfully.", "ms": "Kunci API Gemini berjaya disimpan."},
    "status.key_cleared": {"en": "Gemini API Key cleared.", "ms": "Kunci API Gemini dikosongkan."},
    "status.key_link_opened": {
        "en": "Opened the Gemini API key page in your browser.",
        "ms": "Halaman kunci API Gemini dibuka dalam pelayar anda.",
    },
    "status.engine_auto": {
        "en": "Smart Cloud Mode: Auto-fails over between Gemini 3, 3.8, and 3.5 if free quotas fill up.",
        "ms": "Mod Awan Pintar: Automatis bertukar antara Gemini 3, 3.8 dan 3.5 jika kuota percuma penuh.",
    },
    "status.engine_selected": {
        "en": "Cloud mode selected: Uses {choice} with automatic quota failover protection.",
        "ms": "Mod awan dipilih: Menggunakan {choice} dengan perlindungan pintar kuota.",
    },
    "status.cancelling": {"en": "Cancelling... finishing active operation.", "ms": "Membatalkan... menyiapkan operasi aktif."},
    "status.step1_start": {
        "en": "[Step 1/4] Pre-processing audio (16kHz mono MP3)...",
        "ms": "[Langkah 1/4] Memproses audio (MP3 mono 16kHz)...",
    },
    "status.step1_done": {"en": "[Step 1/4] Audio preprocessing skipped.", "ms": "[Langkah 1/4] Praproses audio dilangkau."},
    "status.step2_start": {
        "en": "[Step 2/4] Preparing audio chunks (checking cache)...",
        "ms": "[Langkah 2/4] Menyediakan potongan audio (semak cache)...",
    },
    "status.step3_cached": {"en": "[Step 3/4] Loaded {chunks} from cache.", "ms": "[Langkah 3/4] Memuatkan {chunks} daripada cache."},
    "status.step3_transcribing": {
        "en": "[Step 3/4] Transcribing {chunks} ({engine})...",
        "ms": "[Langkah 3/4] Mentranskrip {chunks} ({engine})...",
    },
    "status.all_chunks_done": {
        "en": "All chunks completed! Click 'Extract Transcript' in the Monitor window.",
        "ms": "Semua potongan selesai! Klik 'Ekstrak Transkrip' dalam tetingkap Pemantau.",
    },
    "status.batch_finished": {
        "en": "Batch finished: {done}/{total} chunks completed. Please click '↻ Reprocess' on failed chunks.",
        "ms": "Selesai: {done}/{total} potongan siap. Sila klik '↻ Proses Semula' pada potongan gagal.",
    },
    "status.reprocessing_chunk": {"en": "Reprocessing Chunk {index}...", "ms": "Memproses semula Potongan {index}..."},
    "status.reprocess_done": {"en": "Chunk {index} reprocessed successfully!", "ms": "Potongan {index} berjaya diproses semula!"},
    "status.reprocess_failed": {
        "en": "Reprocess of Chunk {index} failed: {error}",
        "ms": "Pemprosesan semula Potongan {index} gagal: {error}",
    },
    "status.extracted": {
        "en": "Extracted transcript ({count} chunks). Ready to generate minutes!",
        "ms": "Transkrip diekstrak ({count} potongan). Sedia untuk menjana minit!",
    },
    "status.step4_start": {
        "en": "[Step 4/4] Generating Meeting Minutes & Action Items ({language})...",
        "ms": "[Langkah 4/4] Menjana Minit Mesyuarat & Tindakan ({language})...",
    },
    "status.all_complete": {
        "en": "Ready. Transcription and meeting minutes completed successfully!",
        "ms": "Sedia. Transkrip dan minit mesyuarat berjaya disiapkan!",
    },
    "status.minutes_failed": {
        "en": "Transcript completed. Minutes generation failed (click Retry).",
        "ms": "Transkrip selesai. Penjanaan minit gagal (klik Cuba Semula).",
    },
    "status.generating_recap": {
        "en": "Generating Executive Meeting Recap ({language})...",
        "ms": "Menjana Rekap Mesyuarat Eksekutif ({language})...",
    },
    "status.recap_complete": {
        "en": "Ready. Executive Meeting Recap completed successfully!",
        "ms": "Sedia. Rekap Mesyuarat Eksekutif berjaya disiapkan!",
    },
    "status.recap_failed": {
        "en": "Recap generation failed: {error}",
        "ms": "Penjanaan rekap gagal: {error}",
    },
    "status.generating_actions": {
        "en": "Generating Action Items ({language})...",
        "ms": "Menjana Senarai Tindakan ({language})...",
    },
    "status.actions_complete": {
        "en": "Ready. Action items completed successfully!",
        "ms": "Sedia. Senarai tindakan berjaya disiapkan!",
    },
    "status.actions_failed": {
        "en": "Action items generation failed: {error}",
        "ms": "Penjanaan senarai tindakan gagal: {error}",
    },
    "status.session_restored": {
        "en": "Restored session for {name} ({chunks}).",
        "ms": "Sesi dipulihkan untuk {name} ({chunks}).",
    },
    "status.session_restored_plain": {
        "en": "Restored previous session from cache!",
        "ms": "Sesi terdahulu dipulihkan daripada cache!",
    },
    "status.chunks_done_suffix": {"en": "{done}/{total} chunks done", "ms": "{done}/{total} potongan selesai"},
    "status.step_prefix": {"en": "[Step {n}/4]", "ms": "[Langkah {n}/4]"},
    "status.step_chunk": {"en": "[Step 3/4] {chunk}: {msg}", "ms": "[Langkah 3/4] {chunk}: {msg}"},
    "status.workspace_reset": {
        "en": "Workspace reset & cache completely cleared. Ready for fresh transcription.",
        "ms": "Ruang kerja diset semula & cache dikosongkan. Sedia untuk transkrip baharu.",
    },
    "status.cancelled": {
        "en": "Operation cancelled by user. Partial progress saved in cache.",
        "ms": "Operasi dibatalkan oleh pengguna. Kemajuan separa disimpan dalam cache.",
    },
    "status.error": {"en": "Error: {error}", "ms": "Ralat: {error}"},

    # --- Minutes error banner ----------------------------------------
    "minutes.banner_idle": {
        "en": "⚠️ Server spike encountered. Your transcript is safe.",
        "ms": "⚠️ Gangguan pelayan dikesan. Transkrip anda selamat.",
    },
    "minutes.banner_error": {
        "en": "⚠️ Minutes failed ({error}...). Transcript is safe.",
        "ms": "⚠️ Minit gagal ({error}...). Transkrip selamat.",
    },
    "recap.banner_error": {
        "en": "⚠️ Recap failed ({error}...). Transcript is safe.",
        "ms": "⚠️ Rekap gagal ({error}...). Transkrip selamat.",
    },
    "actions.banner_error": {
        "en": "⚠️ Action items failed ({error}...). Transcript is safe.",
        "ms": "⚠️ Senarai tindakan gagal ({error}...). Transkrip selamat.",
    },

    # --- Tab content fallbacks ---------------------------------------
    "content.recap_missing": {"en": "Meeting Recap not generated yet. Click 'Generate Recap' to produce one.", "ms": "Rekap Mesyuarat belum dijana. Klik 'Jana Rekap' untuk menjana."},
    "content.actions_missing": {"en": "Action items not generated yet. Click 'Generate Action Items' to produce them.", "ms": "Senarai tindakan belum dijana. Klik 'Jana Senarai Tindakan' untuk menjana."},

    # --- Settings modal ----------------------------------------------
    "settings.title": {"en": "Settings", "ms": "Tetapan"},
    "settings.heading": {"en": "🔑  Gemini API Key", "ms": "🔑  Kunci API Gemini"},
    "settings.help": {
        "en": "Stored locally in .env — never written into session files.",
        "ms": "Disimpan secara lokal dalam .env — tidak pernah ditulis ke fail sesi.",
    },
    "settings.placeholder": {"en": "Enter GEMINI_API_KEY...", "ms": "Masukkan GEMINI_API_KEY..."},
    "settings.get_key": {"en": "🔑  Get a free API key", "ms": "🔑  Dapatkan kunci API percuma"},
    "settings.get_key_hint": {
        "en": "Opens Google AI Studio in your browser",
        "ms": "Membuka Google AI Studio dalam pelayar anda",
    },
    "settings.saved_to": {"en": "Saved to: {path}", "ms": "Disimpan ke: {path}"},
    "settings.audio_heading": {"en": "🎵  Audio Preprocessing", "ms": "🎵  Praproses Audio"},
    "settings.preprocess_chk": {"en": "Pre-process audio (16kHz Mono MP3)", "ms": "Praproses audio (MP3 Mono 16kHz)"},
    "settings.preprocess_help": {
        "en": "Converts audio to 16kHz mono MP3, reducing upload size by 80–90% without loss of speech clarity.",
        "ms": "Menukar audio kepada MP3 mono 16kHz, mengurangkan saiz muat naik sebanyak 80–90% tanpa menjejaskan kejelasan ucapan.",
    },
    "settings.processing_heading": {"en": "🧠  Processing", "ms": "🧠  Pemprosesan"},
    "settings.engine": {"en": "Engine:", "ms": "Enjin:"},
    "settings.chunk": {"en": "Chunk duration:", "ms": "Tempoh potongan:"},
    "settings.chunk_note": {
        "en": "💡 Speaker ID only works with 'No Chunking' (ensures voice consistency).\nRecommended: Use for meetings under 60–90 mins. For longer audio, use chunks (Speaker ID disabled).",
        "ms": "💡 ID Penceramah hanya berfungsi dengan 'Tiada Pemotongan' (menjamin ketepatan suara).\nDisyorkan: Gunakan untuk mesyuarat bawah 60–90 minit. Untuk audio lebih panjang, gunakan potongan (ID Penceramah dimatikan).",
    },
    "chunk.no_chunk": {"en": "No Chunking (Single File)", "ms": "Tiada Pemotongan (Satu Fail)"},
    "msg.speaker_mapping_no_chunk": {
        "en": "Speaker identification is only available when 'No Chunking' is selected in Settings.",
        "ms": "Pengenalpastian penceramah hanya tersedia apabila 'Tiada Pemotongan' dipilih dalam Tetapan.",
    },
    "settings.template": {"en": "Meeting Minute Format:", "ms": "Format Minit Mesyuarat:"},
    "settings.clear": {"en": "🗑  Clear Key", "ms": "🗑  Kosongkan Kunci"},
    "settings.cancel": {"en": "Cancel", "ms": "Batal"},
    "settings.save": {"en": "💾  Save", "ms": "💾  Simpan"},

    # --- About modal -------------------------------------------------
    "about.title": {"en": "About STTMeet", "ms": "Tentang STTMeet"},
    "about.subtitle": {
        "en": "Malaysian Meeting Transcription & Minutes Generator",
        "ms": "Penjana Transkrip & Minit Mesyuarat Malaysia",
    },
    "about.version": {"en": "Version {version}", "ms": "Versi {version}"},
    "about.ffmpeg_installed": {"en": "✅ Installed", "ms": "✅ Dipasang"},
    "about.ffmpeg_missing": {"en": "❌ Not found in PATH", "ms": "❌ Tidak dijumpai dalam PATH"},
    "about.row_ffmpeg": {"en": "FFmpeg", "ms": "FFmpeg"},
    "about.row_transcript_model": {"en": "Transcript model", "ms": "Model transkrip"},
    "about.row_minutes_model": {"en": "Minutes model", "ms": "Model minit"},
    "about.row_data_folder": {"en": "Data folder", "ms": "Folder data"},
    "about.row_cache": {"en": "Session cache", "ms": "Cache sesi"},
    "about.row_log": {"en": "Log file", "ms": "Fail log"},
    "about.close": {"en": "Close", "ms": "Tutup"},

    # --- Chunk monitor dialog ----------------------------------------
    "monitor.header": {"en": "Total Chunks: {total} | Status: Processing...", "ms": "Jumlah Potongan: {total} | Status: Memproses..."},
    "monitor.chunk_title": {"en": "Chunk {index} ({time})", "ms": "Potongan {index} ({time})"},
    "monitor.reprocess": {"en": "↻ Reprocess", "ms": "↻ Proses Semula"},
    "monitor.cancel": {"en": "⏹ Cancel", "ms": "⏹ Batal"},
    "monitor.extract": {"en": "📥 Extract Transcript", "ms": "📥 Ekstrak Transkrip"},
    "monitor.hide": {"en": "Hide Window", "ms": "Sembunyikan Tetingkap"},
    "monitor.locked": {"en": "🔒 Closing Disabled", "ms": "🔒 Tutup Dilumpuhkan"},
    "monitor.close_locked": {
        "en": "This monitor stays open until transcription finishes. Use Cancel to stop the run first.",
        "ms": "Pemantau ini kekal terbuka sehingga transkrip selesai. Gunakan Batal untuk menghentikan proses dahulu.",
    },
    "monitor.state_pending": {"en": "Pending ⚪", "ms": "Menunggu ⚪"},
    "monitor.state_working": {"en": "Transcribing... 🔵", "ms": "Mentranskrip... 🔵"},
    "monitor.state_done": {"en": "Completed 🟢", "ms": "Selesai 🟢"},
    "monitor.state_error": {"en": "Error 🔴", "ms": "Ralat 🔴"},
    "monitor.state_error_detail": {"en": "Error: {detail}... 🔴", "ms": "Ralat: {detail}... 🔴"},
    "monitor.state_cancelled": {"en": "Cancelled ⚪", "ms": "Dibatalkan ⚪"},
    "msg.cancel_nothing": {
        "en": "Nothing to cancel — no transcription is currently running.",
        "ms": "Tiada apa-apa untuk dibatalkan — tiada proses transkrip sedang berjalan.",
    },
    "monitor.summary_base": {
        "en": "Total Chunks: {total} | Completed: {done}/{total}",
        "ms": "Jumlah Potongan: {total} | Selesai: {done}/{total}",
    },
    "monitor.summary_all_done": {
        "en": " | All Chunks Done! Click 'Extract Transcript'",
        "ms": " | Semua Potongan Selesai! Klik 'Ekstrak Transkrip'",
    },
    "monitor.summary_errors": {
        "en": " | Some chunks failed. Click '↻ Reprocess' on red items.",
        "ms": " | Sesetengah potongan gagal. Klik '↻ Proses Semula' pada item merah.",
    },

    # --- Speaker mapping dialog --------------------------------------
    "speakers.title": {"en": "Map Speaker Names", "ms": "Petakan Nama Penceramah"},
    "speakers.assign": {"en": "Assign real names to detected voice tags:", "ms": "Berikan nama sebenar kepada tag suara:"},
    "speakers.placeholder": {"en": "e.g. En. Ahmad / Sarah", "ms": "cth. En. Ahmad / Sarah"},
    "speakers.apply": {"en": "Apply Speaker Names", "ms": "Guna Nama Penceramah"},

    # --- Message boxes: titles ---------------------------------------
    "msg.log_folder": {"en": "Log Folder", "ms": "Folder Log"},
    "msg.success": {"en": "Success", "ms": "Berjaya"},
    "msg.cleared": {"en": "Cleared", "ms": "Dikosongkan"},
    "msg.ffmpeg_warning": {"en": "FFmpeg Warning", "ms": "Amaran FFmpeg"},
    "msg.warning": {"en": "Warning", "ms": "Amaran"},
    "msg.key_link_title": {"en": "Get an API Key", "ms": "Dapatkan Kunci API"},
    "msg.error": {"en": "Error", "ms": "Ralat"},
    "msg.cancel_title": {"en": "Cancel", "ms": "Batal"},
    "msg.partial_extraction": {"en": "Partial Extraction", "ms": "Ekstrakan separa"},
    "msg.extraction_complete": {"en": "Extraction Complete", "ms": "Ekstrakan Selesai"},
    "msg.notice": {"en": "Notice", "ms": "Notis"},
    "msg.busy": {"en": "Busy", "ms": "Sibuk"},
    "msg.save_session": {"en": "Save Session", "ms": "Simpan Sesi"},
    "msg.session_saved": {"en": "Session Saved", "ms": "Sesi Disimpan"},
    "msg.completed": {"en": "Completed", "ms": "Selesai"},
    "msg.transcription_error": {"en": "Transcription Error", "ms": "Ralat Transkrip"},
    "msg.speaker_mapping": {"en": "Speaker Mapping", "ms": "Pemetaan Penceramah"},
    "msg.applied": {"en": "Applied", "ms": "Digunakan"},
    "msg.export": {"en": "Export", "ms": "Eksport"},
    "msg.export_success": {"en": "Export Successful", "ms": "Eksport Berjaya"},

    # --- Message boxes: bodies ---------------------------------------
    "msg.log_folder_body": {"en": "Open this folder manually:\n\n{folder}", "ms": "Buka folder ini secara manual:\n\n{folder}"},
    "msg.key_saved_body": {"en": "Gemini API Key saved successfully.", "ms": "Kunci API Gemini berjaya disimpan."},
    "msg.key_saved_env": {"en": "Gemini API Key saved successfully to .env.", "ms": "Kunci API Gemini berjaya disimpan ke .env."},
    "msg.key_cleared_body": {"en": "Gemini API Key removed from .env.", "ms": "Kunci API Gemini dibuang daripada .env."},
    "msg.key_invalid": {"en": "Please enter a valid Gemini API Key.", "ms": "Sila masukkan Kunci API Gemini yang sah."},
    "msg.key_link_failed": {
        "en": "Could not open your browser automatically.\n\nCreate a free API key here:\n\n{url}",
        "ms": "Pelayar tidak dapat dibuka secara automatik.\n\nCipta kunci API percuma di sini:\n\n{url}",
    },
    "msg.ffmpeg_missing_body": {
        "en": "FFmpeg was not detected in your system PATH.\nPlease ensure FFmpeg is installed to support all audio formats.",
        "ms": "FFmpeg tidak dikesan dalam PATH sistem anda.\nSila pastikan FFmpeg dipasang untuk menyokong semua format audio.",
    },
    "msg.no_audio": {"en": "Please select a valid meeting audio file first.", "ms": "Sila pilih fail audio mesyuarat yang sah terlebih dahulu."},
    "msg.key_required": {
        "en": "Gemini API Key is required. Open ☰ → Settings to add your key.",
        "ms": "Kunci API Gemini diperlukan. Buka ☰ → Tetapan untuk menambah kunci anda.",
    },
    "msg.key_required_plain": {"en": "Gemini API key is required.", "ms": "Kunci API Gemini diperlukan."},
    "msg.key_required_minutes": {
        "en": "Gemini API key is required for minutes synthesis. Open ☰ → Settings.",
        "ms": "Kunci API Gemini diperlukan untuk penjanaan minit. Buka ☰ → Tetapan.",
    },
    "msg.cancel_confirm": {
        "en": "Are you sure you want to cancel the ongoing transcription?",
        "ms": "Adakah anda pasti mahu membatalkan transkrip yang sedang berjalan?",
    },
    "msg.chunk_meta_missing": {"en": "Chunk metadata for index {index} not found.", "ms": "Metadata potongan untuk indeks {index} tidak dijumpai."},
    "msg.partial_chunks": {
        "en": "Chunks {indexes} are not completed yet.\nExtract available completed chunks anyway?",
        "ms": "Potongan {indexes} belum disiapkan.\nEkstrak potongan siap yang ada juga?",
    },
    "msg.extracted_body": {
        "en": "Successfully extracted {count} chunk(s) into the Transcript tab!\nYou can now click '📝 Generate Minutes'.",
        "ms": "Berjaya mengekstrak {count} potongan ke tab Transkrip!\nAnda kini boleh klik '📝 Jana Minit'.",
    },
    "msg.no_transcript": {"en": "No transcript available. Please transcribe audio first.", "ms": "Tiada transkrip tersedia. Sila transkrip audio dahulu."},
    "msg.task_running": {
        "en": "A task is already running. Please wait for it to complete.",
        "ms": "Satu tugas sedang berjalan. Sila tunggu hingga selesai.",
    },
    "msg.save_no_file": {"en": "Please select a valid audio file first.", "ms": "Sila pilih fail audio yang sah terlebih dahulu."},
    "msg.save_while_running": {
        "en": "A task is currently running. Save the session in its current state anyway?",
        "ms": "Satu tugas sedang berjalan. Simpan sesi dalam keadaan semasa juga?",
    },
    "msg.session_saved_body": {"en": "Session saved for:\n{name}", "ms": "Sesi disimpan untuk:\n{name}"},
    "msg.session_save_failed": {
        "en": "Could not write the session file. Check sttmeet.log for details.",
        "ms": "Tidak dapat menulis fail sesi. Semak sttmeet.log untuk butiran.",
    },
    "msg.reset_running": {
        "en": "Cannot reset while a transcription task is currently running.",
        "ms": "Tidak boleh set semula semasa tugas transkrip sedang berjalan.",
    },
    "msg.completed_body": {
        "en": "Meeting transcription, minutes, and action items have been generated!\nYou can now review the tabs or map speaker names before exporting.",
        "ms": "Transkrip mesyuarat, minit dan tindakan telah dijana!\nAnda kini boleh menyemak tab atau memetakan nama penceramah sebelum mengeksport.",
    },
    "msg.transcription_error_body": {"en": "An error occurred:\n{error}", "ms": "Ralat berlaku:\n{error}"},
    "msg.no_speakers_yet": {
        "en": "Please transcribe an audio file first to detect speakers.",
        "ms": "Sila transkrip fail audio dahulu untuk mengesan penceramah.",
    },
    "msg.no_speakers": {"en": "No speakers were detected in the transcript.", "ms": "Tiada penceramah dikesan dalam transkrip."},
    "msg.speakers_applied": {
        "en": "Speaker names updated across transcript and minutes!",
        "ms": "Nama penceramah dikemas kini dalam transkrip dan minit!",
    },
    "msg.export_nothing": {
        "en": "No transcribed content or minutes available to export.",
        "ms": "Tiada kandungan transkrip atau minit untuk dieksport.",
    },
    "msg.export_done": {"en": "Document(s) saved successfully!", "ms": "Dokumen berjaya disimpan!"},
    "msg.minutes_already_generated": {
        "en": "Meeting minutes for '{template}' have already been generated.\n\nRe-generating will call the Gemini API and overwrite the existing minutes for this template.\n\nDo you want to proceed and regenerate?",
        "ms": "Minit mesyuarat untuk '{template}' telah pun dijana sebelum ini.\n\nMenjana semula akan memanggil API Gemini dan menulis ganti minit sedia ada untuk templat ini.\n\nAdakah anda pasti mahu teruskan dan jana semula?",
    },

    # --- Exported document chrome ------------------------------------
    # These were previously hardcoded bilingual ("Tarikh / Date") regardless
    # of the interface language, which made every export read as mixed-language.
    "export.meta_date": {"en": "Date", "ms": "Tarikh"},
    "export.meta_venue": {"en": "Venue", "ms": "Tempat"},
    "export.meta_chair": {"en": "Chair", "ms": "Pengerusi"},
    "export.meta_generated_by": {"en": "Generated by", "ms": "Dijana oleh"},
    "export.venue_default": {"en": "Main Meeting Room / Online", "ms": "Bilik Mesyuarat Utama / Dalam Talian"},
    "export.appendix": {
        "en": "Appendix: Full Audio Transcript",
        "ms": "Lampiran: Transkrip Penuh Audio",
    },
    "export.generated_on": {"en": "Generated on", "ms": "Dijana pada"},
    "export.chair_unknown": {"en": "N/A", "ms": "T/A"},
    "export.docx_missing": {
        "en": "python-docx is not installed.\nPlease install it to export Word documents.",
        "ms": "python-docx tidak dipasang.\nSila pasang untuk mengeksport dokumen Word.",
    },

    # Document titles, keyed by tab. Filename prefixes are intentionally NOT
    # localized (see app_window._export_document) so saved filenames stay
    # stable regardless of the interface language.
    "export.title_transcript": {
        "en": "Audio Transcript - {name}",
        "ms": "Transkrip Audio - {name}",
    },
    "export.title_recap": {
        "en": "Executive Meeting Recap - {name}",
        "ms": "Rekap Mesyuarat Eksekutif - {name}",
    },
    "export.title_actions": {
        "en": "Action Items & Decisions - {name}",
        "ms": "Tindakan & Keputusan - {name}",
    },
    "export.title_minutes": {
        "en": "Meeting Minutes - {name}",
        "ms": "Minit Mesyuarat - {name}",
    },

    # --- Documentation viewer -----------------------------------------
    "docs.window.title": {"en": "Documentation", "ms": "Dokumentasi"},
    "docs.sidebar.title": {"en": "DOCUMENTATION", "ms": "DOKUMENTASI"},
    "docs.source": {"en": "Source: {path}", "ms": "Sumber: {path}"},
    "docs.missing": {
        "en": "No documentation files were found in the docs folder.",
        "ms": "Tiada fail dokumentasi ditemui dalam folder docs.",
    },
    "docs.doc.user_guide": {"en": "User Guide", "ms": "Panduan Pengguna"},
    "docs.doc.meeting_minute.template_descp": {
        "en": "Meeting Minute Formats",
        "ms": "Format Minit Mesyuarat",
    },
    "docs.doc.executive_meeting_recap_template": {
        "en": "Executive Recap",
        "ms": "Rekap Eksekutif",
    },
    "docs.formats.heading": {
        "en": "Meeting Minute Formats",
        "ms": "Format Minit Mesyuarat",
    },
    "docs.formats.lead": {
        "en": "Each format below changes what the generated minutes record. "
              "Pick the one that matches your meeting, then choose it from the "
              "**Meeting Minute Format** dropdown in the Minutes tab.",
        "ms": "Setiap format di bawah mengubah apa yang dicatatkan dalam minit yang dijana. "
              "Pilih format yang sepadan dengan mesyuarat anda, kemudian pilih daripada "
              "menu lungsur **Format Minit Mesyuarat** dalam tab Minit.",
    },
    "docs.formats.short": {"en": "Short Description:", "ms": "Penerangan Ringkas:"},
    "docs.formats.explanation": {"en": "Explanation:", "ms": "Penjelasan:"},
}


def _resolve_mode(entry: Dict[str, str], locale: Optional[str]) -> str:
    """
    Pick the right variant for a locale.

    Falls back to English for an unknown or missing locale so a partially
    translated table can never render as None or an empty label.
    """
    if locale in LOCALES and locale in entry:
        return entry[locale]
    return entry["en"]


def translate(key: str, locale: Optional[str] = None, **fmt: Any) -> str:
    """
    Look up a UI string and format it with `fmt` placeholders.

    Falls back to English when the requested variant is missing so a partial
    translation table can never render as None or an empty label.
    """
    entry = STRINGS.get(key)
    if entry is None:
        raise KeyError(f"Untranslated i18n key: {key!r}")
    text = _resolve_mode(entry, locale)
    return text.format(**fmt) if fmt else text


def has_key(key: str) -> bool:
    return key in STRINGS


def display_minutes_lang(canonical: str, locale: Optional[str] = None) -> str:
    """Display name for a minutes-language value. Never changes the value."""
    entry = MINUTES_LANG_DISPLAY.get(canonical)
    if entry is None:
        return canonical
    return _resolve_mode(entry, locale)


def display_template_name(canonical: str, locale: Optional[str] = None) -> str:
    """Display name for a meeting minute template. Never changes the value."""
    entry = TEMPLATE_DISPLAY.get(canonical)
    if entry is None:
        return canonical
    return _resolve_mode(entry, locale)


def mode_label(mode: str, locale: Optional[str] = None) -> str:
    """
    Label for one of the drawer's language-toggle buttons.

    Ignores `locale` on purpose - these name the modes, not the interface.
    """
    return MODE_NAMES.get(mode, mode)


def normalize_locale(value: Any) -> str:
    """Coerce stored input into a valid locale/mode, defaulting safely."""
    if isinstance(value, str) and value in ALL_MODES:
        return value
    return DEFAULT_LOCALE


def localize_date(moment: datetime, locale: Optional[str] = None) -> str:
    """
    Format a datetime with month names in the requested language.

    strftime("%B") ignores the process locale and always emits English, so the
    Malay variant is assembled by hand from MONTH_NAMES_MS.
    """
    if locale == "ms":
        return f"{moment.day} {MONTH_NAMES_MS[moment.month - 1]} {moment.year}"
    return moment.strftime("%d %B %Y")