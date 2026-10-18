# Changelog

All notable changes to **STTMeet** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [v1.1.0] - 2026-10-18

### Added
- **Time Anchors in Minutes**: Meeting minutes generated across all four templates and both English and Bahasa Melayu now anchor decisions, bullets, and table cells with timestamps (e.g. `(12:34)` or `(1:12:34)`) directly referencing the transcript.
- **Export Toggle for Time Anchors**: Added a switch in the bottom bar beside Export buttons (defaulting to ON and remembered per session) to strip anchors on demand for `.docx`, `.txt`, and Export All while keeping on-screen minutes intact.
- **Headless Pipeline Architecture**: Headless pipeline seam for running transcription and minutes synthesis cleanly without UI dependencies.
- **Minutes Cache Invalidation**: Cached minutes record a cache version to cleanly regenerate older pre-anchor minutes caches.

### Fixed
- **Multi-Timestamp Anchor Export Stripping**: Handled multi-timestamp comma-separated anchors (e.g. `(28:44, 38:00)`) when exporting with the anchor toggle off.

---

## [v1.0.0] - 2026-10-16

### Initial Public Release

Welcome to the first public release of **STTMeet**!

#### 🚀 Features
- **Bahasa Rojak & Code-Switching STT**: Optimized for Malaysian workplace meetings (Bahasa Melayu mixed with English) while preserving colloquial particles (*lah, kan, kot, je, tau*) and corporate/government acronyms.
- **Audio Pre-processing & Chunking**: Automatic silence-based chunking with continuous timestamp synchronization, handling 4-hour+ meeting recordings seamlessly.
- **Gemini Engine Integration**: Multi-model transcription powered by Google Gemini with automatic failover between available models (Gemini 2.5 Flash, Gemini 2.5 Pro).
- **Four Meeting Output Deliverables**:
  - Full timestamped transcript.
  - Interactive speaker diarization & name mapping (`Speaker 1` → participant names).
  - Meeting minutes generated from 4 distinct templates (Action, Discussion/Topical, Three-Column, Board/Governance).
  - Executive recap and structured action item register.
- **Export Options**: Export to Markdown and formatted Microsoft Word documents (`.docx`).
- **Resilience & Checkpointing**: SQLite-backed session store and chunk caching — interrupted runs resume from the last completed chunk without re-transcribing.
- **Standalone Windows Installer**: Packaged setup wizard (`sttmeet_setup.exe`) built with Inno Setup bundling all Python dependencies and FFmpeg.
- **Bilingual Interface**: Native support for English and Bahasa Melayu interface localization.
