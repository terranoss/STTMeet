# 07: Reprocess a single Chunk through the same seam

**What to build:** Reprocessing one failed **Chunk** becomes a second entry on the same interface as the main run, instead of a second copy of the loop. Today a user who retries a single failed chunk gets slightly different behaviour from the main run — **Tail context** and **Overlap** are handled by duplicated logic that has already drifted. After this ticket, a retry produces the same result the main run would have, and the duplication is gone.

The user-visible change is subtle but real: reprocessing a chunk no longer risks leaving duplicated text at a seam, because the same seam handling runs either way.

**Blocked by:** 06 — Move the desktop window onto the pipeline seam

**Status:** ready-for-agent

- [ ] Reprocessing a single **Chunk** is a second entry on the **Pipeline run** interface, not a separate loop
- [ ] **Tail context** is computed the same way on a retry as in the main run
- [ ] **Overlap** is removed the same way on a retry as in the main run
- [ ] A reprocessed chunk's **Transcript** replaces the previous result in the correct position
- [ ] Only one implementation of **Tail context** exists in the codebase
- [ ] Reprocessing remains available from the **Chunk monitor**
- [ ] A reprocessed run still writes its **Checkpoint**
- [ ] Tests cover reprocessing a failed chunk and confirm it yields the same seam handling as a first-pass run
- [ ] The existing suite still passes