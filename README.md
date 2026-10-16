# 🎙️ STTMeet

[![Tests](https://github.com/terranoss/STTMeet/actions/workflows/tests.yml/badge.svg)](https://github.com/terranoss/STTMeet/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D4?logo=windows)](https://github.com/terranoss/STTMeet)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python)](https://www.python.org/)

**High-performance meeting transcription and synthesis for the Malaysian workplace.**

STTMeet turns a long, recorded meeting into a clean timestamped transcript, formatted minutes, an executive recap and an action item register — on your desktop, without re-typing a word.

It is built specifically for **Bahasa Melayu mixed with English ("Bahasa Rojak")**, the code-switched way Malaysian business and government meetings are actually conducted. Global transcription tools routinely mangle this; STTMeet is tuned for it.

---

## ⬇️ Download

[![Download for Windows](https://img.shields.io/badge/%E2%9A%99%20Download_Installer-v1.0.0-2D7D32?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/terranoss/STTMeet/releases/latest/download/sttmeet_setup.exe) [![All Releases](https://img.shields.io/badge/View-All_Releases-24292e?style=for-the-badge&logo=github&logoColor=white)](https://github.com/terranoss/STTMeet/releases)

[Direct Download (`sttmeet_setup.exe`)](https://github.com/terranoss/STTMeet/releases/latest/download/sttmeet_setup.exe) &nbsp;•&nbsp; [All Releases & Changelog](https://github.com/terranoss/STTMeet/releases)


| | |
| :--- | :--- |
| **Platform** | Windows 10 / 11 (x64) |
| **Version** | 1.0.0 |
| **You must install** | Nothing — Python, all dependencies and FFmpeg are bundled |
| **You must bring** | A free or paid [Gemini API key](https://aistudio.google.com/app/apikey) |

> ⚠️ **The installer is not code-signed**, so Windows SmartScreen will show a blue "Windows protected your PC" warning on first run. Click **More info** → **Run anyway**. This is expected for an unsigned community build, not a sign of a problem.

You can also [run from source](#-quick-start) if you'd rather not install anything.

---

## 📸 Screenshot

<img src="assets/img1.png" alt="STTMeet main window — transcript, minutes, recap and action item tabs" width="100%">

---

## 🌟 Why STTMeet?

### 🗣️ Built for Bahasa Rojak
Most speech models are trained on one language at a time and fall apart when a sentence switches mid-clause. STTMeet keeps speech in the exact language it was spoken (Bahasa Melayu + English), retaining Malaysian conversational particles — *lah, kan, kot, je, tau, meh, lor, ya, wei, eh* — and normalising spoken contractions into readable forms (*"tak leh"* → *"tak boleh"*, *"camne"* → *"macam mana"*, *"dorang"* → *"diorang"*). Malaysian acronyms survive intact: *KPI, SOP, PBT, MOF, KWSP, EPF, SSM, LHDN, HRDF, JKR*.

### ⏱️ Built for 4-hour+ meetings
Committee sessions, board meetings and full-day workshops are the normal case, not the edge case. Silence-based chunking with a 5-second overlap keeps continuity across boundaries, and a cache manifest means switching engines never re-slices your audio. Drop your connection mid-run and the job resumes from the last completed chunk — you never re-transcribe what you already paid for.

### 🔁 Survives exhausted quotas
Free-tier Gemini quotas fill up fast. STTMeet automatically fails over across Gemini Flash models when one is throttled, so a rate-limit error doesn't end a two-hour job. You can also pin a specific model for consistent output.

### 📋 Four documents from one recording
You never re-transcribe to get a different document. Each output is generated independently from the transcript already in the workspace, and each can be retried on its own.

| Output | What it gives you |
| :--- | :--- |
| **📝 Transcript** | Full timestamped text with continuous timeline offsets |
| **👥 Speaker mapping** | `Speaker 1` → `En. Ahmad`, applied across transcript and minutes |
| **📄 Minutes** | Four templates: Action, Discussion (Topical), Three-Column, Board/Governance |
| **📌 Executive Recap** | TL;DR, decisions, deliverables, strategic topics, risks |
| **✅ Action Items** | Task, PIC, deadline, status matrix |

### 📄 Exports that are actually presentable
- **Word (`.docx`)** — headings, styled tables and real bold/italic Word formatting. Markdown tables become genuine Word tables; `**bold**` becomes actual bold text, not asterisks.
- **Plain Text (`.txt`)** — fully stripped of Markdown syntax. Headings, tables and lists are converted to clean plain text; no `##`, `**`, or `|` ever reach the file.
- **Markdown (`.md`)** — kept as an option for those who want it.

### 🔐 Privacy-first by design
Your API key stays in a local `.env` and is never written to a session file. Audio is uploaded one chunk at a time and each chunk is deleted from Google's cloud storage immediately after transcription. Everything else — pre-processed audio, per-chunk transcripts, checkpoints, sessions — stays in `.sttmeet_cache/` on your machine.

### 🌐 Bilingual interface
Switch between **English** and **Bahasa Melayu** instantly, with no restart. The choice drives the output language too, and exported documents are localized to match, including their metadata labels and date month names.

---

## ⚙️ How it works

1. **Smart pre-processing.** FFmpeg converts your audio to 16kHz mono MP3 at 64kbps, shrinking a 500MB file to roughly 30MB — an **80–90% reduction** for ~10x faster uploads, with no loss of speech intelligibility.
2. **Hybrid silence-based chunking.** Audio is split on silence rather than blindly by duration, with a 5-second overlap so no sentence is lost on a boundary.
3. **Transcription.** Chunks upload to the Gemini Files API one at a time, each with the previous chunk's closing lines passed in for speaker-label consistency. Transcript generation is configured with `max_output_tokens=65536` so long chunks never truncate mid-sentence.
4. **Synthesis.** Minutes, recap and action items are generated from the finished transcript using a lighter Flash model, to conserve quota.
5. **Cloud hygiene.** Each chunk is deleted from cloud storage as soon as it has been transcribed.

Supported input: `.mp3` `.m4a` `.wav` `.aac` `.ogg` `.flac` `.mp4`

---

## 🚀 Quick start

### Option A — Install the app (recommended)

1. Download `sttmeet_setup.exe` from the [Download](#-download) section above.
2. Run it. SmartScreen will warn — see the note there.
3. Launch **STTMeet** from your Start menu.

### Option B — Run from source

**Prerequisites:** Python 3.10+ (tested on 3.12) and FFmpeg on your `PATH`.

```powershell
git clone https://github.com/terranoss/STTMeet.git
cd STTMeet
pip install -r requirements.txt
python main.py
```

Verify FFmpeg with `ffmpeg -version`. If you don't have it, install it with `winget install Gyan.FFmpeg` or grab a build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/).

---

## 📖 Using the app

1. **Add your API key.** Click **☰** → **⚙️ Settings / Tetapan**, paste your Gemini API key, and click **Save**. The drawer then shows an **API Key configured** badge.
2. **Select audio.** Click **📂 Select Audio File**. Before you spend anything, the app shows total duration, file size, estimated input tokens and approximate Gemini API cost.
3. **Choose options.**
   - **Engine** — ⚡ **Gemini Cloud (Auto-Failover)** (recommended), or pin one model.
   - **Chunk length** — No Chunking (Single File — enables Speaker ID) / 15 / 20 / **25 (recommended)** / 30 / 45 minutes.
   - **Pre-process (16kHz Mono)** — checked by default for ~10x faster uploads.
4. **Start.** Hit **▶ Start** and watch the step badges progress. Open **📊 Monitor Chunks** for per-chunk status (`pending` / `working` / `done` / `error`); **↻ Reprocess** retries a single failed chunk, and **Extract Transcript** pulls completed chunks into the workspace — even from a partial run.
5. **Generate documents.** Each tab generates independently:
   - **Minit Mesyuarat / Minutes** → pick a template → **📝 Generate Minutes**
   - **Rekap Mesyuarat / Meeting Recap** → **📋 Generate Recap**
   - **Senarai Tindakan / Action Items** → **📋 Generate Action Items**
6. **Map speakers.** Click **👥 Map Speaker Names** to replace `Speaker 1` with real names. Do this *before* generating minutes — the generator reads from the transcript, so corrected names flow into every downstream document.
7. **Export.** Click **📄 Export Word (.docx)**, **📃 Export Text (.txt)**, or **📦 Export All**. The Minutes export appends the full transcript as an appendix.
8. **Save and resume.** **💾 Save Session** stores your settings, progress and output; the app also autosaves on chunk completion, on cancel, on speaker mapping and on close. Re-select the same audio file to restore the workspace exactly as you left it. **🔄 Reset** clears everything.

Full details live in the in-app reader: **☰ → 📚 Documentation / Dokumentasi**.

---

## 🪟 Building the Windows installer

```powershell
.\scripts\build_windows.cmd
```

This creates a virtualenv, downloads FFmpeg into `vendor\ffmpeg\bin\`, freezes the app with [PyInstaller](https://pyinstaller.org/) into `sttmeet.dist\`, and compiles **`installer_output\sttmeet_setup.exe`** with [Inno Setup 6](https://jrsoftware.org/isinfo.php).

Build machine requirements: Python 3.10+, `assets\app_icon.ico`, and Inno Setup 6. Nothing else — FFmpeg and all Python dependencies are bundled, and end users install nothing.

To attach the result to the download link at the top of this README, tag a release and attach the installer:

```powershell
git tag v1.0.0
git push origin v1.0.0
# then upload installer_output\sttmeet_setup.exe to the GitHub release
```

Installed builds write data to `%LOCALAPPDATA%\STTMeet` (`.env`, `sttmeet.log`, `.sttmeet_cache\`) because `C:\Program Files` isn't user-writable. The `docs/` folder is bundled so **☰ → 📚 Documentation** works entirely offline.

---

## 📁 Project structure

```text
STTMeet/
├── main.py                     # Application entry point with launch notifications
├── requirements.txt            # Python dependencies (google-genai, customtkinter, python-docx, ...)
├── .env.example                # Template for GEMINI_API_KEY
├── .gitignore                  # Ignores caches, .env, audio, temp chunks
├── .gitattributes              # Line-ending normalization (LF) & binary declarations
├── LICENSE                     # MIT License
├── SECURITY.md                 # Vulnerability reporting & secret-handling guidance
├── test_pipeline.py            # Unit tests for logic, post-processing & session store
│
├── assets/
│   ├── app_icon.ico            # Application + installer icon
│   └── img1.png                # README screenshot
│
├── scripts/
│   ├── build_windows.cmd       # One-command Windows installer build
│   ├── build_windows.ps1       # PyInstaller freeze + FFmpeg fetch + Inno Setup compile
│   └── sttmeet_setup.iss       # Inno Setup 6 installer definition
│
├── docs/                       # Read in-app via ☰ → 📚 Documentation
│   ├── user_guide.md           # End-user guide (workflow + template selection)
│   ├── executive_meeting_recap_template.md
│   └── meeting_minute/
│       ├── template_descp.txt  # In-app format descriptions
│       └── *_template.md       # Prompt specs for developers (not shown in-app)
│
├── .github/
│   ├── workflows/tests.yml     # CI: unit tests on Python 3.10 & 3.12
│   └── ISSUE_TEMPLATE/         # Bug report & feature request forms
│
├── src/
│   ├── __init__.py
│   ├── version.py              # Application version (single source of truth for builds)
│   ├── config.py               # Settings manager (API keys, paths, chunk & model settings)
│   ├── logger.py               # Centralized rotating file logger
│   ├── utils.py                # FFmpeg checker, audio duration, token & cost estimator
│   ├── audio_processor.py      # Preprocessing (16kHz MP3), silence detection, hybrid chunking
│   ├── gemini_transcriber.py   # Files API upload, polling, prompting, failover, cleanup
│   ├── transcript_processor.py # Timestamp shifting, overlap dedup, speaker mapping
│   ├── minutes_generator.py    # Multi-template synthesis (English / Bahasa Melayu)
│   ├── recap_generator.py      # Executive meeting recap synthesis
│   ├── exporter.py             # Word (.docx), Markdown (.md) & Text (.txt) exports
│   ├── session_store.py        # Session save/restore (settings, status, output)
│   ├── i18n.py                 # UI chrome + export label translations (English / Bahasa Melayu)
│   ├── prefs.py                # Global preferences (interface language)
│   │
│   └── ui/
│       ├── __init__.py
│       ├── app_window.py       # CustomTkinter GUI: layout, tabs, chunk monitor, workers
│       └── docs_viewer.py      # Built-in offline documentation reader
│
└── .sttmeet_cache/             # Auto-generated: chunks, checkpoints, sessions, prefs
```

---

## 🔐 Privacy & data

- Your API key lives only in a local `.env` file. It is never written to a session file and never committed — see [SECURITY.md](SECURITY.md).
- Audio is uploaded to the Google Gemini API one chunk at a time; each chunk is deleted from cloud storage immediately after transcription.
- Pre-processed audio, per-chunk transcripts, checkpoints and sessions stay on your machine in `.sttmeet_cache/`.
- **🔄 Reset** purges the workspace and the local cache.

---

## 🧪 Running unit tests

```powershell
pip install -r requirements.txt
python test_pipeline.py
```

Expected output:

```text
All unit tests passed successfully!
```

The suite is pure logic — no API key, no network, no GUI. It covers timestamp math, overlap deduplication, speaker mapping, cost estimation, session save/restore, and the Markdown-to-plain-text export conversion. Tests run on every push via [GitHub Actions](.github/workflows/tests.yml) against Python 3.10 and 3.12.

---

## 🤝 Contributing

Issues and feature requests are welcome via [.github/ISSUE_TEMPLATE](.github/ISSUE_TEMPLATE). If you find a security vulnerability, please **do not** open a public issue — follow [SECURITY.md](SECURITY.md).

---

## 📄 License

Released under the [MIT License](LICENSE). Built with the [Google Gemini API](https://ai.google.dev/gemini-api) and [CustomTkinter](https://github.com/tomschubo/customtkinter).