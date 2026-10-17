# 06: Move the desktop window onto the pipeline seam

**What to build:** The desktop window becomes the second caller of the **Pipeline run** instead of owning it. Everything the window shows during a run — step badges, status text, progress percentage — is driven by what the **Pipeline run** reports, rather than by the run reaching into the window as it goes. After this ticket, the window and the headless entry point are two adapters over one orchestration, and a user cannot tell which one produced their **Transcript**.

This also closes two real defects. Today the worker thread reads interface variables from off-thread, which the code's own snapshot mechanism was written to prevent — so a session save during a run could touch the interface from the wrong thread. After this ticket there is no interface variable left to read, because settings are taken as data at the start of the run.

This is the largest ticket in the set. It changes how the window drives a run without changing what a user sees.

**Blocked by:** 04 — Run a whole Audio file headlessly, with Chunking off; 05 — Chunk, checkpoint and resume on the headless path

**Status:** ready-for-agent

- [ ] The window starts a **Pipeline run** through the seam and does not own the loop
- [ ] Step badges, status text and progress percentage are driven entirely by reports from the run
- [ ] The **Chunk monitor** and the live **Transcript** view are updated from reports, not from state the run mutates in place
- [ ] Settings are captured once at the start of a run and reused for its whole duration
- [ ] No interface variable is read from a worker thread anywhere in the run's path
- [ ] Session save never touches the interface from the worker thread
- [ ] Cancelling from the window stops every stage promptly
- [ ] A failed **Chunk** stays resumable rather than being marked failed for good
- [ ] Saving and restoring a session behaves as it does today, restoring **Transcript** and **Minutes**
- [ ] Closing the window autosaves the session as it does today
- [ ] The pipeline module imports nothing from the desktop UI package, and a test enforces that
- [ ] The window's observable behaviour is unchanged: same steps, same badges, same live view, same autosave
- [ ] The existing suite still passes