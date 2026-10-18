# 02: Anchors in every Template and language, and pre-anchor sessions regenerate

**What to build:** Every **Template** carries **time anchors** in both **Processing languages**, so a Bahasa Melayu meeting gets them as surely as an English one. Headless output carries them too, since the headless path writes its own files and never consults the export writers. A session whose **Minutes** were cached before **time anchors** existed regenerates on next use rather than showing a document where the feature appears to do nothing.

**Blocked by:** 01 — Prove time anchors on one Template.

**Status:** ready-for-agent

- [ ] All four **Template** prompts, in both **Processing languages**, carry the **time anchor** rule stated in the prompt's own language.
- [ ] Anchors close bullets, prose sentences, and table cells. Headings and the metadata block stay clean, including the **Date & Time** field, so a meeting time is never confused with an anchor.
- [ ] Table cells carry anchors, including in the three-column **Template** — a **Template** that is one large table would otherwise ship with no anchors at all.
- [ ] Minutes past one hour render anchors in hour form.
- [ ] Headless output carries anchors, with no command-line switch and no separate code path added.
- [ ] Cached **Minutes** record a version, and an entry written before **time anchors** existed reads as a miss so the next generation produces anchors.
- [ ] A session saved and reloaded with the current cache version still uses its cached **Minutes**.
- [ ] The prompt seam test is extended to assert the anchor rule is present in all eight prompts, in both languages, without pinning its wording.
- [ ] The cache version is asserted at the session seam: current version is used, older version reads as a miss.
- [ ] Every new test is registered in the suite's entry point, and the full existing suite still passes.