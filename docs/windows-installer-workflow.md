# Windows Installer Workflow

How to go from STTMeet source changes to a shippable Windows installer.

**One command (primary):**

```powershell
.\scripts\build_windows.cmd
```

**Primary deliverable:** [`installer_output\sttmeet_setup.exe`](../installer_output/sttmeet_setup.exe) (gitignored; created on your machine)

**Toolchain:** [PyInstaller](https://pyinstaller.org/) freeze of `main.py` into `sttmeet.dist\`, then [Inno Setup 6](https://jrsoftware.org/isinfo.php) via [`scripts/sttmeet_setup.iss`](../scripts/sttmeet_setup.iss).

---

## Overview

```
Python (dev/test)  ->  PyInstaller (sttmeet.dist\)  ->  Inno Setup (installer_output\sttmeet_setup.exe)  ->  GitHub Release
```

- Day-to-day feature testing: run with Python (`python main.py`). You do not need the installer to develop.
- Shipping to users: run `.\scripts\build_windows.cmd` and distribute `installer_output\sttmeet_setup.exe`.
- End users need **nothing else**. FFmpeg/ffprobe are bundled and installed into the app folder; Gemini is reached over HTTPS.

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Windows | Build machine |
| Python 3.10+ | Same interpreter used for the freeze |
| `venv/` | Created by the build script if missing |
| `assets\app_icon.ico` | Required; the build fails loudly if absent |
| Inno Setup 6 | Provides `ISCC.exe` (required for the installer step) |
| Internet | Only on the build machine (pip + FFmpeg download) |

> **Fast & Reliable Packaging:** The project uses PyInstaller (`--onedir`) which freezes dependencies like `google-genai` and `customtkinter` in under a minute without needing a heavy C++ compiler workload on the build machine.

---

## Workflow (in order)

### 1. Develop and test with Python

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Confirm transcription, chunk monitor, speaker mapping, and Word/Markdown/Text exports.

### 2. Bump the version

Edit [`src/version.py`](../src/version.py):

```python
__version__ = "1.0.0"  # example
```

The window title, the installer UI, and the Windows file version all read this value. Keep the git tag in sync (`v1.0.0`).

### 3. Build the Windows installer

```powershell
.\scripts\build_windows.cmd
```

What this does:

1. Ensures `.\venv` and dependencies (skips pip if packages already import)
2. Downloads FFmpeg into `vendor\ffmpeg\bin\` (skipped if `ffmpeg.exe` + `ffprobe.exe` already exist)
3. Freezes with Nuitka into `sttmeet.dist\` (parallel `--jobs`, MSVC backend, tk-inter plugin, bundled package data)
4. Compiles **`installer_output\sttmeet_setup.exe`** with Inno Setup

Optional flags:

| Flag | Meaning |
|------|---------|
| `-InstallerOnly` | Skip Nuitka; package the existing `sttmeet.dist\` and `vendor\` only |
| `-SkipInstaller` | Freeze only; do not run Inno Setup |
| `-UpdateDeps` | Force `pip install` of requirements + Nuitka |
| `-UpdateFfmpeg` | Re-download FFmpeg even if it is already in `vendor\` |
| `-OneFile` | Also emit a single-file exe (slower startup; not required for the installer) |
| `-UseGcc` | Use gcc/MinGW instead of MSVC (fails on `google.genai`; only for diagnosing the freeze) |

### 4. Smoke-test the installer

On a clean Windows machine:

1. Run `installer_output\sttmeet_setup.exe` and install
2. Launch STTMeet from the Start menu
3. Confirm the FFmpeg badge is green without any FFmpeg being installed on the machine
4. Enter your Gemini API key, transcribe a short clip, export a `.docx`
5. Confirm app data was created: `%LOCALAPPDATA%\STTMeet\` containing `.env`, `sttmeet.log`, `.sttmeet_cache\`
6. Confirm the install layout: `{autopf}\STTMeet\runtime\sttmeet.exe` with `runtime\ffmpeg\ffmpeg.exe`
7. Re-run the installer (repair/upgrade), then uninstall and choose whether to keep app data

### 5. Tag and publish

```powershell
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions does **not** build the installer — upload `installer_output\sttmeet_setup.exe` manually (`gh release upload` or the GitHub UI).

---

## Build artefacts (all gitignored)

| Path | Meaning |
|------|---------|
| `sttmeet.build\` | Nuitka intermediate tree |
| `sttmeet.dist\` | Standalone app folder (input to Inno Setup; installed under `{autopf}\STTMeet\runtime\`) |
| `vendor\ffmpeg\bin\` | Bundled `ffmpeg.exe` / `ffprobe.exe` (input to Inno Setup) |
| `installer_output\sttmeet_setup.exe` | **Ship this** |
| `nuitka-crash-report.xml` | Nuitka diagnostics if something fails |

Do not commit these.

---

## Where installed builds write data

The install directory (`C:\Program Files`) is not writable by standard users, so a frozen build redirects its data paths:

| Path | Development | Installed build |
|------|-------------|-----------------|
| `.env` (Gemini API key) | repo root | `%LOCALAPPDATA%\STTMeet\.env` |
| `.sttmeet_cache\` (chunks, checkpoints, sessions) | repo root | `%LOCALAPPDATA%\STTMeet\.sttmeet_cache\` |
| `sttmeet.log` | repo root | `%LOCALAPPDATA%\STTMeet\sttmeet.log` |

Detection is `sys.frozen` / Nuitka's `__compiled__`, implemented in [`src/config.py`](../src/config.py). The uninstaller offers to delete `%LOCALAPPDATA%\STTMeet` after removing the program, but never deletes it silently.

---

## Bundled FFmpeg

`src/config.py :: get_bundled_ffmpeg_dir()` returns:

- installed: the `ffmpeg\` folder next to `sttmeet.exe` (i.e. `{app}\runtime\ffmpeg`)
- development: `vendor\ffmpeg\bin` if present, otherwise nothing

`ensure_ffmpeg_on_path()` prepends that folder to `PATH` once per process, so `pydub`, `preprocess_audio()`, `check_ffmpeg()` and `get_audio_duration()` all resolve the bundled binaries. If the folder is missing, STTMeet falls back to a system FFmpeg on `PATH` exactly as before.

The build downloads the **essentials build from gyan.dev**. That build is GPL-licensed; keep the `vendor\ffmpeg` contents out of git and note the FFmpeg obligation in your distribution terms if you ship it.

---

## When to update Python

Only when you intentionally change the freeze interpreter (e.g. 3.10 to 3.12). Then recreate the venv, reinstall deps, re-test with Python, and re-run `.\scripts\build_windows.cmd`.

Normal releases: bump version -> Python test -> `build_windows.cmd` -> tag -> upload installer.

---

## Release checklist

- [ ] Features tested with `python main.py`
- [ ] `__version__` bumped in `src/version.py`
- [ ] `assets\app_icon.ico` present
- [ ] `.\scripts\build_windows.cmd` completed successfully
- [ ] `installer_output\sttmeet_setup.exe` exists
- [ ] Installer smoke-tested on a clean machine (FFmpeg badge green, API key saved, `.docx` export)
- [ ] Git tag `vX.Y.Z` pushed (optional)
- [ ] `sttmeet_setup.exe` uploaded to the GitHub Release (optional)