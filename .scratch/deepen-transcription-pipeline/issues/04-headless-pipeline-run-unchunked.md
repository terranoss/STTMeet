# 04: Run a whole Audio file headlessly, with Chunking off

**What to build:** A user can transcribe a recording and get **Minutes** from a terminal, without opening the desktop app. The orchestration that currently exists only as methods on the window — the **Pipeline run** — becomes callable on its own, taking its settings as data and reporting what it is doing to something that can print. This is the first complete headless path: an **Audio file** with **Chunking** off goes in, and a **Transcript** plus **Minutes** come out on disk.

This is deliberately the narrowest version that is still real. It proves the **Pipeline run** is reachable without a window, and that two callers can share it — the window and a headless entry point. Chunking, resume and cancellation arrive in the next ticket, once the path is proven end to end.

**Blocked by:** 03 — Move transcription onto the shared failover policy

**Status:** ready-for-agent

- [ ] The **Pipeline run** is callable without constructing any window or importing the desktop UI package
- [ ] The **Pipeline run** takes its settings as a plain data object, not from interface variables
- [ ] Progress and per-**Chunk** status are reported through one channel, distinguished by phase
- [ ] Reports carry a translation key and formatting arguments, not finished sentences
- [ ] No message the headless path emits requires a translation table to produce
- [ ] A headless flag on the existing entry point transcribes an **Audio file** and writes **Transcript** and **Minutes** to disk
- [ ] The headless run honours the **Engine** choice and **Processing language**
- [ ] The headless run's settings default to what the desktop app persists
- [ ] A test drives a whole **Pipeline run** through the seam with a recording observer and a fake transcription client, asserting only what the observer saw
- [ ] Importing the **Pipeline run** pulls in no UI toolkit
- [ ] The existing suite still passes