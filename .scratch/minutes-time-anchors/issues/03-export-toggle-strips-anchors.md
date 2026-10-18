# 03: Export toggle strips time anchors on request

**What to build:** A switch beside the **Export** buttons controls whether **time anchors** reach the exported document. It is on by default and remembered per session. With it off, the Word, text, and **Export All** documents come out clean, while the **Minutes** tab keeps showing anchors — so flipping it back on restores them instantly, with no regeneration and no cost.

**Blocked by:** 01 — Prove time anchors on one Template.

**Status:** ready-for-agent

- [ ] A switch renders beside the **Export** buttons, on by default, with a label in the **Interface language**.
- [ ] The setting is stored in the per-session settings and survives closing and reopening the session.
- [ ] A session written before the setting existed loads with the documented default rather than failing.
- [ ] With the switch off, anchors are absent from the Word **Export**, the text **Export**, and **Export All**.
- [ ] With the switch on, the exported documents are byte-for-byte what they are today.
- [ ] Switching does not alter the **Minutes** shown on screen in either position.
- [ ] Stripping applies only on the **Minutes** branch. The **Transcript** **Export** keeps its own markers, and **Recap** and **Action items** exports are untouched.
- [ ] The **Transcript** appendix appended to a Minutes Word **Export** keeps its markers — those are the **Transcript**'s own, not **time anchors**.
- [ ] A stripped table still parses into the same rows and columns, and bold spans and pipes survive stripping.
- [ ] The behaviour is asserted by writing to a temporary directory and reading the result back — on the written text, and for Word on the paragraph and table text read back through the document library. No seam is added to the strip transform itself; it is covered through the export.
- [ ] This is the first test in the suite that asserts on exported content; the export module's conversion logic is no longer untested.
- [ ] Every new test is registered in the suite's entry point, and the full existing suite still passes.