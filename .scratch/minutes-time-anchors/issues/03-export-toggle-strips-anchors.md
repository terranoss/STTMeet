# 03: Export toggle strips time anchors on request

**What to build:** A switch beside the **Export** buttons controls whether **time anchors** reach the exported document. It is on by default and remembered per session. With it off, the Word, text, and **Export All** documents come out clean, while the **Minutes** tab keeps showing anchors — so flipping it back on restores them instantly, with no regeneration and no cost.

**Blocked by:** 01 — Prove time anchors on one Template.

**Status:** resolved

- [x] A switch renders beside the **Export** buttons, on by default, with a label in the **Interface language**.
- [x] The setting is stored in the per-session settings and survives closing and reopening the session.
- [x] A session written before the setting existed loads with the documented default rather than failing.
- [x] With the switch off, anchors are absent from the Word **Export**, the text **Export**, and **Export All**.
- [x] With the switch on, the exported documents are byte-for-byte what they are today.
- [x] Switching does not alter the **Minutes** shown on screen in either position.
- [x] Stripping applies only on the **Minutes** branch. The **Transcript** **Export** keeps its own markers, and **Recap** and **Action items** exports are untouched.
- [x] The **Transcript** appendix appended to a Minutes Word **Export** keeps its markers — those are the **Transcript**'s own, not **time anchors**.
- [x] A stripped table still parses into the same rows and columns, and bold spans and pipes survive stripping.
- [x] The behaviour is asserted by writing to a temporary directory and reading the result back — on the written text, and for Word on the paragraph and table text read back through the document library. No seam is added to the strip transform itself; it is covered through the export.
- [x] This is the first test in the suite that asserts on exported content; the export module's conversion logic is no longer untested.
- [x] Every new test is registered in the suite's entry point, and the full existing suite still passes.