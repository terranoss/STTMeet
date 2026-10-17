# 08: Unify the three generation triggers

**What to build:** Generating **Minutes**, **Recap** or **Action items** independently — without re-running the whole pipeline — goes through one templated method instead of three near-identical blocks. A maintainer fixing a bug in the shape of a generation run then fixes it once rather than three times.

This also closes a defect. The minutes path, which is reachable both from the pipeline's completion and from its own button, does not restore interface state on every exit path. If a late step fails there, the controls stay disabled and the app looks stuck. The unified method always restores them.

**Blocked by:** 06 — Move the desktop window onto the pipeline seam

**Status:** ready-for-agent

- [ ] **Minutes**, **Recap** and **Action items** generation share one templated method, differing only in what they call and what they display
- [ ] Each generation path's progress reporting, error display and view refresh are supplied as data rather than reimplemented
- [ ] The unified method restores interface state on every exit path, including success, failure, and cancellation
- [ ] A failure late in the minutes path no longer leaves controls disabled
- [ ] **Minutes** generated from the pipeline's completion and from its own button behave identically
- [ ] A cancelled generation leaves the app in the same usable state as a failed one
- [ ] The unified method restores state on the path that currently has no restore at all
- [ ] The existing suite still passes
- [ ] Tests confirm each of the three paths reports progress and surfaces errors, without reaching into widget internals