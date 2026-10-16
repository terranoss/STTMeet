# STTMeet User Guide

STTMeet turns a recorded meeting into a clean, formatted transcript, meeting
minutes, an executive recap and an action item register — without leaving your
desktop.

This guide walks through the whole workflow, then explains each meeting minute
template so you can pick the right one for your meeting.

---

## 1. Before You Start

| Requirement | Notes |
| :--- | :--- |
| Gemini API Key | Required. Stored locally in `.env`, never uploaded anywhere else. |
| FFmpeg | Required for audio preprocessing. Verify with `ffmpeg -version`. |
| Supported audio | `.mp3`, `.m4a`, `.wav`, `.aac`, `.ogg`, `.flac`, `.mp4` |

Open the **Tools** menu → **Settings...** (or the ⚙️ toolbar icon), paste
your Gemini API Key and click **Save**. A green **API Key configured** badge
appears in the status bar, so you can always confirm the app is ready before
starting a long transcription.

---

## 2. The Four Output Tabs

STTMeet never makes you re-transcribe audio to get a different document. Each
output is generated independently from the transcript already in the workspace.

| Tab | What you get | When to use it |
| :--- | :--- | :--- |
| **Transcript** | Timestamped text with speaker labels | Verbatim record, evidence, quotations |
| **Minutes** | Formatted minutes in your chosen template | Circulating the official record |
| **Meeting Recap** | Short executive summary for leaders | Pre-reads and senior updates |
| **Action Items** | Owner / deliverable / due date register | Follow-up and accountability |

---

## 3. Step-by-Step Workflow

### Step 1 — Select the audio
Click **📂 Select Audio File**. The app shows the total duration, file size,
estimated input tokens and the approximate Gemini API cost before you spend
anything.

### Step 2 — Choose your options

| Option | Guidance |
| :--- | :--- |
| **Engine** | **⚡ Gemini Cloud (Auto-Failover)** is recommended; it retries on a fallback model if the primary one is rate limited. |
| **Chunk length** | 25 min is the sweet spot. Shorter chunks recover faster from a single failure; longer ones cost slightly less. |
| **Pre-process (16kHz Mono)** | Leave checked. It shrinks the upload by roughly 10x and speeds up transcription. |

### Step 3 — Start and monitor
Click **▶ Start** and watch the step badges progress through preprocessing,
chunking, transcription and assembly.

Open **📊 Monitor Chunks** to see the status of every chunk individually. If one
chunk fails, click **↻ Reprocess** on that chunk alone — you never pay to redo
the whole meeting. When the chunks you need are done, click **Extract
Transcript** to pull them into the workspace.

### Step 4 — Map the speakers
Click **👥 Map Speaker Names** and replace labels such as `Speaker 1` with real
names (`Speaker 1` → `En. Razak`). Do this *before* generating minutes if you
can: the generator works from the transcript, so correct names flow into the
minutes, recap and action items automatically.

### Step 5 — Generate the minutes
Open the **Minutes** tab, choose a **Meeting Minute Format** from the dropdown,
then click **📝 Generate Minutes**. See the next section for how to choose.

### Step 6 — Generate the recap and action items
Use **📋 Generate Recap** and **📋 Generate Action Items** in their respective
tabs. Each can be retried on its own.

### Step 7 — Export and save

* **📄 Export Word (.docx)** — styled document; the Minutes export also appends
  the full transcript as an appendix.
* **📝 Export Text (.txt)** — plain text.
* **📦 Export All** — every tab in one pass.
* **💾 Save Session** — stores settings, progress and output. The app also
  autosaves at chunk completion, on cancel, on speaker mapping and on close.

Re-select the same audio file later and the workspace is restored exactly as you
left it. **🔄 Reset** clears the workspace and purges the local cache.

---

## 4. Choosing a Meeting Minute Template

The **Meeting Minute Format** dropdown decides the *structure* of the generated
document. It is set in the Minutes tab and in **⚙️ Settings**, and it is
remembered between sessions.

| Template | Structure | Best for |
| :--- | :--- | :--- |
| **Action Minutes** *(default)* | Narrative sections plus an action item register table | Most operational and project meetings |
| **Discussion (Topical)** | Topic-by-topic deliberation log | Workshops, panels, research and consultation sessions |
| **Three-Column** | One row per item: discussion, action, responsibility | Dense agendas where every line must have an owner |
| **Board / Governance** | Formal board minute numbering with resolutions | Company boards, committees, governance bodies |

Open the **Tools** menu → **Documentation** (or the 📚 toolbar icon) and
select **Meeting Minute Formats** for the full description of each one —
what it records, and the kind of meeting it suits.

### 4.1 Action Minutes *(default)*
Sections: meeting objective, review of prior action items, agenda items with
decisions, an **action item register** table, and next meeting details.

Choose this when decisions must be traceable against earlier commitments — the
"Review of Prior Action Items" section is what closes the loop with the previous
meeting.

### 4.2 Discussion Minutes (Topical)
Sections: per-topic deliberation records capturing arguments, alternatives
considered and points of agreement, followed by a decisions summary.

Choose this when the *reasoning* matters more than the outcome — a committee
weighing options, or a consultation where you need a record of what was said and
why.

### 4.3 Three-Column Minutes
One table with three columns: **Discussion & Deliberation**, **Action Required
& Decision**, and **Responsibility & Deadline**.

Choose this for execution-focused meetings — site coordination, contractor or
vendor reviews — where every agenda row must leave with a named lead and a date.

### 4.4 Board / Governance Minutes
Numbered resolutions, formal voting records, declarations of interest and a
director attendance table.

Choose this only when the meeting is a formal governing body. It is deliberately
rigid and expects quorum, voting and minute-taking conventions that an ordinary
project meeting does not have.

### 4.5 Executive Recap *(separate tab)*
A one-page brief for people who will not read the minutes: key decisions,
commitments made and what happens next. It is not a template of the Minutes tab
and is generated from the same transcript.

---

## 5. Reading the Template Fields

Every template starts with a metadata block. Fill these in the recording where
you can, otherwise state them at the top of the meeting:

* **Meeting Title / Date & Time / Location** — the meeting's identity.
* **Chairperson / Minute Taker** — who led the meeting and who wrote it up.
* **Attendees / Absentees** — the record of who was present; often required for
  quorum.

Inside the body, two conventions matter most:

* **Square brackets** like `[Owner]` are placeholders the generator fills from
  the transcript. If the meeting never names an owner, the field stays generic —
  review it before circulating.
* **Every action needs three things:** what is to be done, who owns it, and by
  when. If the meeting agrees on the *what* but not the *who*, add the owner
  yourself afterwards.

---

## 6. Interface Language

The **EN/MS** chip in the toolbar switches the interface between **English**
and **Bahasa Melayu**,
and the minutes output language follows the interface language automatically.
The **🌐 Output** chip always shows the language currently used for generation.

Switching languages re-labels the whole app, including this documentation
reader.

---

## 7. Troubleshooting

| Symptom | What to do |
| :--- | :--- |
| **FFmpeg not found** | Install FFmpeg, or run `.\scripts\build_windows.cmd` once to vendor it into `vendor\ffmpeg\bin\`. |
| **A chunk fails** | Open **📊 Monitor Chunks** and use **↻ Reprocess** on that chunk only. |
| **Transcript is empty** | Increase the silence threshold or shorten the chunk length in Settings, then reprocess. |
| **Speaker names are generic** | The recording did not identify speakers clearly. Use **👥 Map Speaker Names** before generating minutes. |
| **Minutes miss a detail** | The audio was ambiguous. Fix the transcript source or edit the exported document directly. |
