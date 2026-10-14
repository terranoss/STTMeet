# 🎙️ STTMeet

[![Tests](https://github.com/Deen/STTMeet/actions/workflows/tests.yml/badge.svg)](https://github.com/Deen/STTMeet/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**STTMeet** is a Windows desktop application that transcribes long Malaysian business and government meeting recordings (up to 4+ hours or more) conducted in **Bahasa Melayu mixed with English ("Bahasa Rojak")** using **Google Gemini 3 / 3.8 / 3.5 Flash**, with automatic failover between models when free quotas fill up.

It automatically generates:
- 📝 **Full Timestamped Transcript** with continuous timeline offsets.
- 👥 **Speaker Diarization & Name Mapping** (`Speaker 1`, `Speaker 2` -> `En. Ahmad`, `Pn. Sarah`).
- 📌 **Executive Summary / Ringkasan Eksekutif**.
- 💡 **Discussion Highlights / Perkara-Perkara Yang Dibincangkan**.
- ⚖️ **Key Decisions Made / Keputusan Mesyuarat**.
- 📋 **Action Items Matrix / Matriks Tindakan** (Task, PIC, Deadline, Status).
- 💾 **Executive-Ready Exports**: Microsoft Word (`.docx`), Markdown (`.md`), and Plain Text (`.txt`).

---

## 🌟 Key Architecture & Features

### 1. Robust 4+ Hour Audio Pipeline
- **Flexible Gemini Model Selection:** Pick **⚡ Gemini Cloud (Auto-Failover)** to let STTMeet automatically move between Gemini 3, 3.8, and 3.5 when free quotas fill up, or pin a specific model for consistent output.
- **Smart Pre-Processing (16kHz Mono MP3):** Automatically converts bulky audio formats to 16kHz Mono MP3 at 64kbps using FFmpeg. This reduces file size by **80–90%** (e.g. 500MB becomes ~30MB) for **10x faster cloud uploads** with zero loss of speech intelligibility.
- **Hybrid Silence-Based Chunking with Cache Manifest:** Slices audio into manageable segments using silence detection with a **5-second boundary overlap**. Chunks are cached via manifest so switching engines never re-slices audio.
- **Output Token Safety:** Configured with `max_output_tokens=65536` to prevent transcript truncation mid-sentence.
- **Automatic Checkpointing & Resumption:** Intermediate transcripts are cached locally in `.sttmeet_cache/`. If your internet drops or you cancel midway, the job resumes from the last completed chunk without re-transcribing earlier audio.
- **Session Persistence:** Press **💾 Save Session** to snapshot the settings used (model, minutes language, chunk size, pre-processing), the pipeline status (step badges + per-chunk state), and the output (transcript, minutes, speaker names) into `.sttmeet_cache/session_<hash>.json`. The app also autosaves on chunk completion, on cancel, on speaker mapping, and on close — re-select the same audio file to pick the workspace back up exactly as you left it. Your API key is never written to the session file.
- **Cloud Hygiene:** Uploaded audio chunks in Google Files API are automatically deleted immediately after transcription to avoid cloud clutter and storage costs.

### 2. Tuned for Malaysian "Bahasa Rojak"
- **Natural Code-Switching:** Keeps speech in the exact language it was spoken (BM + English), without forced translations.
- **Malaysian Particles:** Retains characteristic conversational particles (*lah, kan, kot, je, tau, meh, lor, ya, wei, eh*).
- **Conversational Normalization:** Normalizes spoken contractions into standard readable forms (*"tak leh"* -> *"tak boleh"*, *"camne"* -> *"macam mana"*, *"dorang"* -> *"diorang"*).
- **Acronym Accuracy:** Preserves Malaysian government, business, and tech acronyms (*KPI, SOP, PBT, MOF, KWSP, EPF, SSM, LHDN, HRDF, JKR*).

### 3. Speaker Continuity & Interactive Name Mapping
- **Voice Consistency:** Passes the closing lines of the previous chunk into the prompt for the next chunk to maintain consistent speaker labeling across boundaries.
- **Interactive Mapping:** Click **👥 Map Speaker Names** in the app to assign real participant names to voice tags across both the transcript and final minutes. Applied names are saved with the session and reappear in the dialog next time.

### 4. Live Chunk Monitor
- **📊 Monitor Chunks** opens a floating panel showing per-chunk state (`pending` / `working` / `done` / `error`) with an overall completion count.
- A single failed chunk can be reprocessed with **↻ Reprocess** without re-running the whole meeting, and **Extract Transcript** pulls every completed chunk into the main workspace in order — even from a partial run.

---

## 📸 Screenshots

<!-- TODO: add screenshots to docs/ and reference them here, e.g.
<img src="docs/screenshots/main-window.png" alt="Main window" width="800">
-->

---

## 📁 Project Structure

```text
STTMeet/
├── main.py                     # Application entry point with launch notifications
├── requirements.txt            # Python dependencies (google-genai, customtkinter, etc.)
├── .env.example                # Template for GEMINI_API_KEY
├── .gitignore                  # Git ignore rules (caches, .env, audio, temp chunks)
├── .gitattributes              # Line-ending normalization (LF) & binary declarations
├── LICENSE                     # MIT License
├── SECURITY.md                 # Vulnerability reporting & secret-handling guidance
├── README.md                   # Project documentation
├── test_pipeline.py            # Unit tests for logic, post-processing & session store
│
├── assets/
│   └── app_icon.ico            # Application + installer icon
│
├── scripts/
│   ├── build_windows.cmd       # Entry point: one-command Windows installer build
│   ├── build_windows.ps1       # Nuitka freeze + FFmpeg fetch + Inno Setup compile
│   └── sttmeet_setup.iss       # Inno Setup 6 installer definition
│
├── docs/
│   └── windows-installer-workflow.md  # Build, smoke-test and release guide
│
├── .github/
│   ├── workflows/tests.yml     # CI: unit tests on Python 3.10 & 3.12
│   └── ISSUE_TEMPLATE/         # Bug report & feature request forms
│
├── src/
│   ├── __init__.py
│   ├── version.py              # Application version (read by the build script & UI)
│   ├── config.py               # Settings manager (API keys, paths, chunk & model settings)
│   ├── logger.py               # Centralized rotating file logger
│   ├── utils.py                # FFmpeg checker, audio duration, token & cost estimator
│   ├── audio_processor.py      # Preprocessing (16kHz MP3), silence detection, hybrid chunking
│   ├── gemini_transcriber.py   # Google GenAI Files API upload, polling, prompting, failover, cleanup
│   ├── transcript_processor.py # Continuous timestamp shifting, overlap dedup, speaker mapping
│   ├── minutes_generator.py    # Multi-language synthesis (Malay, English, Bilingual)
│   ├── exporter.py             # Formatted Word (.docx), Markdown (.md), and Text (.txt) exports
│   ├── session_store.py        # Session save/restore (settings, status, output)
│   │
│   └── ui/
│       ├── __init__.py
│       └── app_window.py       # CustomTkinter GUI layout, tabs, chunk monitor, worker threads
│
└── .sttmeet_cache/             # Auto-generated local cache for chunks, checkpoints & sessions
```

---

## 🛠️ Installation & Setup

### Step 1: Clone Repository
```powershell
git clone https://github.com/Deen/STTMeet.git
cd STTMeet
```

### Step 2: Prerequisites
1. **Python 3.10+** (Tested on Python 3.12).
2. **FFmpeg**: Must be installed and accessible in your system `PATH`.
   - Verify by running:
     ```powershell
     ffmpeg -version
     ```
   - *If not installed, install via `winget install Gyan.FFmpeg` or download from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/).*
   - Alternatively, run `.\scripts\build_windows.cmd` once — it vendors FFmpeg into `vendor\ffmpeg\bin\`, which the app also prefers over `PATH`.

### Step 3: Install Dependencies
```powershell
pip install -r requirements.txt
```

---

## 🚀 How to Run

Launch the desktop application:
```powershell
python main.py
```

### Usage Steps:
1. **Enter API Key:** Paste your **Gemini API Key** into the top field and click **Save Key** (saved securely to `.env`, never committed).
2. **Select Audio:** Click **📂 Select Audio File** (`.mp3`, `.m4a`, `.wav`, `.aac`, `.ogg`, `.flac`, `.mp4`). The app displays:
   - Total duration
   - File size
   - Estimated input tokens
   - Approximate Gemini API cost
3. **Choose Options:**
   - **Engine:** **⚡ Gemini Cloud (Auto-Failover)** (recommended) or pin a specific Gemini model.
   - **Minutes Lang:** Bahasa Melayu, English, or Bilingual.
   - **Chunk:** 15 / 20 / 25 (recommended) / 30 / 45 minutes.
   - **Pre-process (16kHz Mono):** Checked by default for ~10x faster uploads.
4. **Click ▶ Transcribe Audio:**
   - Watch live progress on the step badges and progress bar.
   - Click **📊 Monitor Chunks** to see per-chunk status; use **↻ Reprocess** on any failed chunk, then **Extract Transcript** to pull completed chunks into the workspace.
5. **Generate Minutes:**
   - Click **📝 Generate Minutes** for the Executive Summary, Discussion Points, Decisions and Action Items Matrix — this can be retried on its own without re-transcribing.
   - Review the **Transkrip Penuh**, **Minit Mesyuarat**, **Ringkasan** and **Senarai Tindakan** tabs.
6. **Map Speakers & Export:**
   - Click **👥 Map Speaker Names** to assign names (e.g. `Speaker 1` -> `En. Razak`).
   - Click **📄 Export Word (.docx)**, **📝 Export Markdown (.md)**, or **📦 Export All**.
7. **Save & Resume:**
   - Click **💾 Save Session** to store the settings, status and output. The app also autosaves at chunk completion, on cancel, on speaker mapping and on close.
   - Re-select the same audio file later to restore the workspace exactly as you left it.
   - Click **🔄 Reset** to clear the workspace and purge the local cache.

---

## 🪟 Building the Windows Installer

Ship a single installer that bundles Python, the app and FFmpeg:

```powershell
.\scripts\build_windows.cmd
```

This creates/uses `venv\`, downloads FFmpeg into `vendor\ffmpeg\bin\`, freezes the app with [Nuitka](https://nuitka.net/) into `sttmeet.dist\`, and compiles **`installer_output\sttmeet_setup.exe`** with [Inno Setup 6](https://jrsoftware.org/isinfo.php).

Requirements on the build machine: Python 3.10+, an `assets\app_icon.ico`, **Visual Studio Build Tools (C++ workload)** — `google-genai`'s generated C is too large for gcc's assembler — and Inno Setup 6. Nothing else: FFmpeg is fetched automatically and end users do not need to install anything.

Installed builds write their data to `%LOCALAPPDATA%\STTMeet` (`.env`, `sttmeet.log`, `.sttmeet_cache\`) because `C:\Program Files` is not user-writable.

See [docs/windows-installer-workflow.md](docs/windows-installer-workflow.md) for flags, artefacts, smoke-testing and the release checklist.

---

## 🔐 Privacy & Data

- Your API key lives only in a local `.env` file. It is never written to a session file and never committed — see [SECURITY.md](SECURITY.md).
- Audio is uploaded to the Google Gemini API one chunk at a time; each chunk is deleted from cloud storage immediately after it is transcribed.
- Everything else — pre-processed audio, per-chunk transcripts, checkpoints and sessions — stays on your machine in `.sttmeet_cache/`.

---

## 🧪 Running Unit Tests

Run the built-in test suite to verify timestamp math, deduplication, speaker mapping, cost estimation and session save/restore:

```powershell
pip install -r requirements.txt
python test_pipeline.py
```
Expected output:
```text
All unit tests passed successfully!
```

The tests are pure logic — no API key, no network and no GUI required. They run on every push via [GitHub Actions](.github/workflows/tests.yml).

---

## 📄 License

Released under the [MIT License](LICENSE). Built with the Google Gemini API (Gemini 3 / 3.8 / 3.5 Flash) and CustomTkinter.
