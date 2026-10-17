# 05: Chunk, checkpoint and resume on the headless path

**What to build:** A headless **Pipeline run** handles a long **Audio file** the way the desktop app does: it **Chunks** the audio at silence boundaries, carries **Tail context** across each **Chunk** seam, removes **Overlap**, writes a **Checkpoint** after every chunk, resumes from that **Checkpoint** if interrupted, and stops promptly when the user cancels. A user who interrupts a three-hour meeting with Ctrl+C and restarts should not re-pay for the **Chunks** already transcribed.

This is the resilience that makes the headless path trustworthy for the meeting lengths this app exists for. Until now none of it was testable, because it lived on a widget.

**Blocked by:** 04 — Run a whole Audio file headlessly, with Chunking off

**Status:** ready-for-agent

- [ ] **Chunking** splits a long **Audio file** at silence boundaries when enabled, and is skipped entirely when disabled
- [ ] **Tail context** carries the last few lines of the previous **Chunk**'s transcript into the next, so speaker names and phrasing stay continuous across the seam
- [ ] **Overlap** is removed from the seam between chunks
- [ ] A **Checkpoint** is written after each completed **Chunk**, recording which are done and what they transcribed
- [ ] An interrupted run resumes from its **Checkpoint** and skips work already done, including re-seeding **Tail context** from cached text
- [ ] A cancelled run leaves its remaining chunks resumable rather than marking them failed
- [ ] A cancelled run stops promptly between chunks
- [ ] Ctrl+C cancels a headless run cleanly
- [ ] **Transcript** assembly orders completed chunks correctly
- [ ] Tests cover resume-skip, tail-context continuity across a seam, overlap removal, and cancellation mid-run — with no provider call and no window
- [ ] A test drives a **Pipeline run** through the seam with a fake transcription client that fails partway, then resumes
- [ ] The existing suite still passes