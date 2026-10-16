# Security Policy

## Reporting a Vulnerability

**Please do not open a public issue for security problems.**

Meeting minutes and transcripts handled by STTMeet are frequently confidential
(government, board, HR and legal discussions). If you find a vulnerability that
could expose transcripts, API keys, or cached audio, report it privately:

1. Go to the repository's **Security** tab on GitHub.
2. Click **Report a vulnerability**.
3. Describe the issue, the affected version, and how to reproduce it.

You can expect an acknowledgement within a few days. Please give reasonable time
for a fix before disclosing publicly.

## Handling Secrets

- Your Gemini API key is stored **only** in a local `.env` file, which is listed
  in `.gitignore` and excluded from this repository by `.gitignore` rules and
  `.env.example` being the only committed template.
- **Never** commit a real API key, a `.env` file, raw meeting audio, or exported
  meeting documents. All of these are covered by `.gitignore`, but gitignore is
  not a substitute for care — check `git status` before every commit.
- If you ever commit a real API key by accident, **rotate it immediately** in
  Google AI Studio. Removing the file in a later commit does not un-expose it.

## Data Handled by the Application

STTMeet processes meeting audio entirely on your machine except for the audio
chunks it uploads to the Google Gemini API for transcription. Audio chunks
uploaded for a chunk are deleted from cloud storage immediately after that
chunk is transcribed.

Local artifacts — pre-processed audio, per-chunk transcripts, checkpoints and
saved sessions — live in `.sttmeet_cache/`. This folder is gitignored. Clear it
from inside the app with the **🔄 Reset** button, or delete the folder directly.

## Audio Formats Accepted

`.mp3`, `.m4a`, `.wav`, `.aac`, `.ogg`, `.flac`, `.mp4`. Files are converted to
16kHz mono MP3 before upload when **Pre-process (16kHz Mono)** is enabled.