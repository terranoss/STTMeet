# STTMeet

STTMeet turns a recorded meeting into a verbatim transcript and a set of structured meeting documents. It exists for people who sit through long meetings in Bahasa Melayu or English and need an accurate record without typing it up.

## Language

### Recording and transcription

**Audio file**:
The single recording handed to STTMeet for one meeting. Identified throughout by a **file hash** so a re-run of the same recording can resume rather than restart.
_Avoid_: input, source file, upload

**Preprocessing**:
Converting an audio file to the 16kHz mono form the transcription service requires. Optional — a recording already in that shape can skip it.
_Avoid_: cleaning, normalization, conversion step

**Chunk**:
A time-bounded slice of one audio file, produced by **preprocessing**'s successor, chunking. A long meeting becomes many chunks because a single request cannot carry it.
_Avoid_: segment, part, piece, slice

**Chunking**:
Splitting an audio file into **chunks** at silence boundaries, so a speaker's turn is not cut in half. Off by default; a recording that fits in one request skips it entirely.
_Avoid_: splitting, segmentation

**Tail context**:
The last few lines of the previous **chunk**'s transcript, passed alongside the next chunk so the transcription service keeps speaker names and phrasing continuous across the seam.
_Avoid_: overlap, carry-over, leading context

**Overlap**:
Text appearing in both a **chunk**'s transcript and its predecessor's, caused by the **chunking** boundary landing mid-sentence. Removed by deduplication.
_Avoid_: duplication, repeated text

**Checkpoint**:
The on-disk record of which **chunks** are done and what they transcribed, written after each one. Lets an interrupted meeting resume instead of re-paying for work already done.
_Avoid_: cache, autosave, progress file, resume file

**Pipeline run**:
One complete pass over a single **audio file** from preprocessing through transcript assembly.
_Avoid_: job, session, task, process

### Gemini and models

**Failover chain**:
The ordered list of models to try for one request. The user's **engine** choice sets the first entry; the rest are the fallbacks.
_Avoid_: model list, model chain, retry list

**Engine**:
What the user picks to say which model leads the **failover chain** for both transcription and **minutes synthesis**. Defaults to auto-failover, where no model is pinned.
_Avoid_: model, provider, backend

**Quota failure**:
The provider signalling it has refused this request for the day, rather than for a transient fault. Distinct from an ordinary error: it ends the **failover chain** immediately instead of retrying.
_Avoid_: rate limit, 429, throttle

**Diarization**:
Asking the model to label who is speaking. Available only on models that support it, so a **chunk** too short to hold two speakers gains nothing from it.
_Avoid_: speaker detection, speaker labelling

### Documents

**Transcript**:
The verbatim, timestamped record of what was said, assembled from every completed **chunk** in order.
_Avoid_: raw output, verbatim, full audio transcript

**Minutes**:
The structured meeting record generated from the **transcript** — discussion, decisions, action items. What most people actually want from the meeting.
_Avoid_: summary, recap, notes, report

**Template**:
The chosen shape of the **minutes**: what sections appear and what the model is asked to produce. Four exist, all named in Malay in the interface.
_Avoid_: format, style, layout

**Recap**:
A one-page executive brief distilled from the **transcript**, aimed at someone who did not attend. Distinct from **minutes**, which aim at someone who did.
_Avoid_: executive summary, abstract, brief

**Action items**:
The list of commitments extracted from the **transcript**, each with an owner and a due date where the meeting stated one.
_Avoid_: tasks, to-dos, next steps

**Action minutes**:
A **template** for **minutes** centred on tracking **action items** across meetings rather than recording discussion.
_Avoid_: action item template, actions template

**Speaker mapping**:
The substitution of real names for the model's placeholder speaker tags, where the meeting makes the attribution clear.
_Avoid_: speaker renaming, name mapping

**Time anchor**:
The `(MM:SS)` marker closing a **minutes** bullet, prose sentence or table cell, pointing to where in the **transcript** that content was recorded. Written by the model, and absent where it had nothing to point at — a **minutes** document may carry no anchors at all.
_Avoid_: timestamp, citation, time reference

**Export**:
Writing a **transcript**, **minutes**, **recap** or **action items** out as a Word or plain-text document. May or may not carry **time anchors**, which is a property of the **export** rather than of the **minutes** it was written from.
_Avoid_: download, save-as, output

## Language discipline

**Processing language**:
The language the **minutes** are written in. It cascades from the interface language but is set independently — the interface can be English while the **minutes** are Malay.
_Avoid_: output language, target language

**Interface language**:
The language the STTMeet window is displayed in.
_Avoid_: UI language, locale, display language

**Filename prefix**:
The fixed word prepended to an **export**'s filename ("Transkrip", "Minit"). Deliberately does not change with the **interface language**, so saved filenames stay stable when the user switches language mid-meeting.
_Avoid_: export prefix, title prefix