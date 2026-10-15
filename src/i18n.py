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

from typing import Any, Dict, Optional

# Single-language locales plus a combined mode that shows "Malay / English",
# which preserves the app's original inline bilingual appearance.
LOCALES = ("en", "ms")
COMBINED = "both"
ALL_MODES = LOCALES + (COMBINED,)
DEFAULT_LOCALE = COMBINED

# Names of the three language modes. These label the toggle buttons themselves,
# so they are intentionally not localized: "Bahasa Melayu" is the same word in
# both languages, and translating them would produce "Bahasa Melayu / Bahasa
# Melayu" nonsense in the combined mode.
MODE_NAMES = {
    "en": "English",
    "ms": "Bahasa Melayu",
    "both": "Both",
}

# UI locale -> minutes language value stored in lang_var.
# lang_var's values are validated by session_store.VALID_LANGUAGES and are used
# as dict keys to pick a Gemini prompt, so these are canonical and untranslated.
MINUTES_LANG_BY_UI_LOCALE = {
    "en": "English",
    "ms": "Bahasa Melayu",
    "both": "Bilingual",
}

# Display-only names for the read-only output-language chip. Never written back
# to lang_var. test_pipeline.py asserts the keys match VALID_LANGUAGES exactly.
MINUTES_LANG_DISPLAY = {
    "Bahasa Melayu": {"en": "Bahasa Melayu", "ms": "Bahasa Melayu"},
    "English": {"en": "English", "ms": "Inggeris"},
    "Bilingual": {"en": "Bilingual", "ms": "Dwibahasa"},
}

TEMPLATE_DISPLAY = {
    "action_minutes": {
        "en": "Action Minutes",
        "ms": "Minit Tindakan",
        "both": "Minit Tindakan / Action Minutes"
    },
    "discussion_minutes": {
        "en": "Discussion (Topical)",
        "ms": "Perbincangan (Topikal)",
        "both": "Perbincangan / Discussion"
    },
    "three_column": {
        "en": "Three-Column",
        "ms": "Tiga Lajur",
        "both": "Tiga Lajur / Three-Column"
    },
    "board_governance": {
        "en": "Board / Governance",
        "ms": "Lembaga Pengarah / Tadbir Urus",
        "both": "Lembaga Pengarah / Board"
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
    "Bilingual",
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
    "control.engine": {"en": "Engine:", "ms": "Enjin:"},
    "control.chunk": {"en": "Chunk:", "ms": "Potongan:"},
    "control.template": {"en": "Meeting Minute Format:", "ms": "Format Minit Mesyuarat:"},
    "control.preprocess": {"en": "Pre-process (16kHz Mono)", "ms": "Praproses (16kHz Mono)"},
    "control.output_lang": {"en": "🌐 Output: {value}", "ms": "🌐 Keluaran: {value}"},
    "btn.transcribe": {"en": "▶ Transcribe Audio", "ms": "▶ Transkrip Audio"},
    "btn.generate_minutes": {"en": "📝 Generate Minutes", "ms": "📝 Jana Minit"},
    "btn.cancel": {"en": "⏹ Cancel", "ms": "⏹ Batal"},
    "btn.monitor": {"en": "📊 Monitor Chunks", "ms": "📊 Pantau Potongan"},
    "btn.reset": {"en": "🔄 Reset", "ms": "🔄 Set Semula"},
    "btn.save_session": {"en": "💾 Save Session", "ms": "💾 Simpan Sesi"},
    "btn.retry_minutes": {"en": "↻ Retry Generation", "ms": "↻ Cuba Jana Semula"},
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

    # --- Tabs (explicit 'both' keeps today's Malay-first order) -------
    "tab.transcript": {
        "en": "Transcript", "ms": "Transkrip Penuh",
        "both": "Transkrip Penuh / Transcript",
    },
    "tab.minutes": {
        "en": "Minutes", "ms": "Minit Mesyuarat",
        "both": "Minit Mesyuarat / Minutes",
    },
    "tab.summary": {
        "en": "Summary", "ms": "Ringkasan",
        "both": "Ringkasan / Summary",
    },
    "tab.actions": {
        "en": "Action Items", "ms": "Senarai Tindakan",
        "both": "Senarai Tindakan / Action Items",
    },

    # --- Status bar ---------------------------------------------------
    "status.ready": {
        "en": "Ready. Select an audio file and click Transcribe Audio.",
        "ms": "Sedia. Pilih fail audio dan klik Transkrip Audio.",
    },
    "status.log_opened": {"en": "Opened log folder: {folder}", "ms": "Folder log dibuka: {folder}"},
    "status.key_saved": {"en": "Gemini API Key saved successfully.", "ms": "Kunci API Gemini berjaya disimpan."},
    "status.key_cleared": {"en": "Gemini API Key cleared.", "ms": "Kunci API Gemini dikosongkan."},
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

    # --- Tab content fallbacks ---------------------------------------
    "content.summary_missing": {"en": "Summary not generated.", "ms": "Ringkasan tidak dijana."},
    "content.actions_missing": {"en": "No action items extracted.", "ms": "Tiada tindakan diekstrak."},

    # --- Settings modal ----------------------------------------------
    "settings.title": {"en": "Settings", "ms": "Tetapan"},
    "settings.heading": {"en": "🔑  Gemini API Key", "ms": "🔑  Kunci API Gemini"},
    "settings.help": {
        "en": "Create a key at https://aistudio.google.com/apikey\nStored locally in .env — never written into session files.",
        "ms": "Cipta kunci di https://aistudio.google.com/apikey\nDisimpan secara lokal dalam .env — tidak pernah ditulis ke fail sesi.",
    },
    "settings.placeholder": {"en": "Enter GEMINI_API_KEY...", "ms": "Masukkan GEMINI_API_KEY..."},
    "settings.saved_to": {"en": "Saved to: {path}", "ms": "Disimpan ke: {path}"},
    "settings.audio_heading": {"en": "🎵  Audio Preprocessing", "ms": "🎵  Praproses Audio"},
    "settings.preprocess_chk": {"en": "Pre-process audio (16kHz Mono MP3)", "ms": "Praproses audio (MP3 Mono 16kHz)"},
    "settings.preprocess_help": {
        "en": "Converts audio to 16kHz mono MP3, reducing upload size by 80–90% without loss of speech clarity.",
        "ms": "Menukar audio kepada MP3 mono 16kHz, mengurangkan saiz muat naik sebanyak 80–90% tanpa menjejaskan kejelasan ucapan.",
    },
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
    "monitor.state_pending": {"en": "Pending ⚪", "ms": "Menunggu ⚪"},
    "monitor.state_working": {"en": "Transcribing... 🔵", "ms": "Mentranskrip... 🔵"},
    "monitor.state_done": {"en": "Completed 🟢", "ms": "Selesai 🟢"},
    "monitor.state_error": {"en": "Error 🔴", "ms": "Ralat 🔴"},
    "monitor.state_error_detail": {"en": "Error: {detail}... 🔴", "ms": "Ralat: {detail}... 🔴"},
    "monitor.state_cancelled": {"en": "Cancelled ⚪", "ms": "Dibatalkan ⚪"},
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
}


def _leading_symbol(text: str) -> str:
    """Leading emoji/symbol token of a string, or '' if it starts with a word."""
    token = text.split(" ", 1)[0]
    if token and not any(ch.isalnum() for ch in token):
        return token
    return ""


def _join_both(en: str, ms: str) -> str:
    """
    Combine two variants for COMBINED mode.

    A shared leading emoji ("▶ Transcribe Audio" / "▶ Transkrip Audio") is
    dropped from the second half so the icon is not rendered twice.
    """
    symbol = _leading_symbol(en)
    if symbol and symbol == _leading_symbol(ms):
        return f"{en} / {ms[len(symbol):].strip()}"
    return f"{en} / {ms}"


def _resolve_mode(entry: Dict[str, str], locale: Optional[str]) -> str:
    """
    Pick the right variant for a locale.

    For COMBINED, an explicit "both" string wins; otherwise the two languages
    are joined. This lets entries that were Malay-first before localization
    (the tab captions) keep their original word order.
    """
    if locale == COMBINED:
        if "both" in entry:
            return entry["both"]
        en = entry.get("en")
        ms = entry.get("ms")
        if en and ms:
            return _join_both(en, ms)
        return en or ms or ""
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