Status: ready-for-agent

# Time anchors in Minutes, with an export toggle

## Problem Statement

Someone reading a set of **Minutes** has no way to tell *where in the meeting* a point came from. The **Minutes** are a faithful account of what was decided and who owns what, but every statement in it is unanchored — the reader either believes it or has to go hunting through the **Transcript** tab to find the moment it was discussed.

This matters most for **Action minutes**, where the reader is checking whether a commitment is real. "Priya to circulate the revised budget by Friday" is a claim; Priya's own words at 22:14 are proof.

The **Transcript** already solves this problem for itself. Every spoken turn is prefixed with a marker, so anyone reading the **Transcript** can see exactly when a thing was said. The **Minutes** throw that information away, even though the markers are still present in the text handed to the model.

There is a second gap. When a **Minutes** document is **Exported**, the reader has no choice about how much scaffolding travels with it. Some recipients want the trail back to the recording; others want a clean document that reads as a finished record and nothing more. Today the export formats are fixed and the user has no say.

## Solution

Every bullet, prose sentence, and table cell in a **Minutes** document ends with a **time anchor** — `(12:34)`, or `(1:12:34)` once the meeting passes an hour — pointing at the point in the **Transcript** where that content was recorded. Headings and the metadata block stay clean, because those record the shape of the meeting rather than its content.

The **Minutes** tab always shows the anchors. Whether they reach the exported document is the user's choice, controlled by a single on/off switch beside the **Export** buttons.

## User Stories

1. As someone reading the **Minutes** after a long meeting, I want each point to carry the time it was discussed, so that I can judge a claim without searching the **Transcript**.
2. As someone verifying a commitment in an **Action minutes** document, I want to see the moment the owner agreed to it, so that I can tell a real commitment from an inferred one.
3. As a chair preparing minutes for absent attendees, I want anchors on discussion points, so that an absentee can jump to the recording at the moment a contentious item was raised.
4. As a reader of a **board governance** minute, I want anchors on motions and resolutions, so that I can check the wording of a vote against what was actually said.
5. As a reader of a three-column minute, I want anchors in the discussion cells, so that the deliberation column is traceable to the **Transcript**.
6. As someone reviewing a **Template**, I want anchors on every **Action item**, so that a due date can be traced back to the discussion that set it.
7. As a user, I want anchors to appear on bullets, prose, and table cells alike, so that the trail is consistent regardless of which section I am reading.
8. As a user, I want headings and the metadata block left clean, so that the document's structure is not cluttered by markers.
9. As a user, I want the minute's date and time fields left clean, so that a **Date & Time** of `10:30 AM` is never confused with a **time anchor**.
10. As a user, I want anchors formatted consistently with the **Transcript**'s own markers, so that one reading of the time format serves both documents.
11. As a user, I want meetings past one hour to show hours, so that a ninety-minute meeting does not produce a nonsensical `75:00`.
12. As a user, I want an item the model cannot place in time to carry no anchor at all, so that the document never shows a placeholder that looks like a defect.
13. As a user, I want the **Minutes** tab to always show anchors, so that the feature is visible without me hunting for a setting.
14. As a user, I want an **Export** toggle beside the **Export** buttons, so that I control the trail at the moment I write the document out.
15. As a user, I want the toggle to apply to the Word **Export**, so that my `.docx` carries the trail when I want it.
16. As a user, I want the toggle to apply to the text **Export**, so that my `.txt` carries the trail when I want it.
17. As a user, I want the toggle to apply to the combined **Export All**, so that I do not have to set it twice.
18. As a user, I want the toggle to default to on, so that the feature works without me opting in to it.
19. As a user, I want the toggle setting to survive closing and reopening the session, so that I do not reset it every meeting.
20. As a user, I want turning the toggle off not to alter the **Minutes** I see on screen, so that I can switch it back on and get the anchors back immediately.
21. As a user, I want turning the toggle off to be instant, so that I do not pay for another generation to change how a document is written out.
22. As a user, I want turning the toggle off to affect only the **Minutes**, so that my **Recap** and **Action items** exports are untouched.
23. As a user, I want the **Transcript** **Export** untouched by the toggle, so that the transcript's own markers are never stripped.
24. As a user, I want the toggle to remain visible on every tab, so that I can find it wherever the **Export** buttons are.
25. As someone sending minutes to an external party, I want a clean **Export** in one click, so that I can hand over a finished record rather than a working document.
26. As someone keeping an internal record, I want an anchored **Export** in one click, so that the trail survives outside the app.
27. As a user, I want the toggle label in my **Interface language**, so that the control reads naturally to me.
28. As a user working in Bahasa Melayu, I want anchors in **Minutes** written in Bahasa Melayu, so that the feature works in the **Processing language** I chose.
29. As a user, I want anchors in all four **Templates**, so that the feature is not limited to one shape of minutes.
30. As a user running a headless meeting, I want anchors in the written **Minutes**, so that the scripted path produces the same document as the window.
31. As a user with minutes cached from an earlier run, I want those minutes regenerated once so that anchors are not silently missing, so that the feature does not appear broken.
32. As a developer, I want the prompt rule that produces **time anchors** stated in both languages, so that neither **Processing language** gets anchors by accident.
33. As a developer, I want the documented **Template** shapes updated to match the prompts, so that the reference developers read is not stale.
34. As a developer, I want a check that the documented shapes match the prompts, so that future edits to a heading cannot silently invalidate the documentation.
35. As a user, I want the **Minutes** tab to remain readable with anchors present, so that markers do not make the document hard to read.

## Implementation Decisions

**The anchors are produced by the model, not computed afterwards.** The **Transcript** is a flat string whose turns are already prefixed with time markers, and that string reaches the synthesis prompt unmodified. The change is therefore a rule added to the synthesis prompts — no new pipeline stage, no change to how the **Transcript** is assembled or chunked.

**All eight synthesis prompts change.** Four **Templates** by two **Processing languages**. Each gains a rule stating where anchors go, what they look like, and that an item with nothing to point at gets none. The rule is stated in the prompt's own language, not in English with a translated gloss.

**Anchor format.** Parenthesised, so it reads as an aside rather than as structure: `(12:34)` under an hour, `(1:12:34)` at or over an hour. The hour form switches on the same boundary the **Transcript** uses. Anchors close the bullet, sentence, or cell they belong to.

**Coverage is deliberately uneven.** Bullets, prose sentences, and table cells carry anchors. Headings and the metadata block do not. The three-column **Template** is a single table, so excluding table cells would leave that **Template** with no anchors at all — the feature would look broken there.

**Cells are expected to get wider.** The three-column **Template** packs four columns into a rendered width the markdown renderer already scales to fit. Anchors in every cell will make that table denser. This is accepted in exchange for consistency across **Templates**; if it proves unreadable in practice, restricting anchors to the discussion column is the cheap fallback.

**The toggle is an export-time transform, not a generation setting.** The **Minutes** document always carries anchors. Turning the toggle off strips them on the way to the exported file. This keeps the switch instant, costs nothing, and keeps the on-screen **Minutes** intact so the anchors can be restored by flipping the switch back.

**The strip is a pure text transform over the markdown**, applied before the content reaches the Word and text writers. It must remove an anchor whether it terminates a bullet, a line of prose, or a table cell, and must leave the surrounding markdown — bold spans, pipes, alignment rows — untouched so that table rendering still works downstream.

**The strip is scoped to the Minutes branch of the export path.** The **Transcript** carries its own markers and is never stripped. **Recap** and **Action items** are one-page briefs aimed at readers who were not in the room; they are not part of this change. The full **Transcript** appendix appended to a Minutes Word **Export** is likewise left intact — its markers are the **Transcript**'s own, not **time anchors**.

**The toggle defaults to on and persists.** It is a boolean in the per-session settings, so it survives closing and reopening the meeting. It renders as a switch in the bottom bar beside the **Export** buttons, and stays visible on every tab — on the tabs where it has no effect it is inert, which is preferable to hiding and re-laying-out the bar as the user changes tabs.

**Cached Minutes carry a version marker.** A cached **Minutes** document generated before **time anchors** existed has none, and stripping it is a no-op — the toggle would appear to do nothing with no explanation. The cache entry records the anchor version, and an entry at an older version reads as a miss so the next generation produces anchors.

**The headless path carries anchors unconditionally.** Headless writes its own files and never goes through the export writers, so the toggle cannot reach it. Headless is the same product with a different front door, and anchors are part of the **Minutes** document rather than a presentation choice. No command-line switch is added.

**Documentation is updated, and a check is added to keep it honest.** Each **Template** has a reference document describing its section structure. These already drift from the prompts in small ways. They are updated as part of this work, and a check compares the section headings in each prompt against the corresponding reference document.

**The check compares section headings only.** Headings define a **Template**'s shape, which is what the reference documents exist to convey. Full-text comparison would fail on placeholder wording that differs harmlessly between the two copies and would force rewrites for no benefit. The check also asserts it found all four **Templates** and a non-trivial heading count for each, so a broken parse cannot produce a silent pass.

**Nothing about section bucketing changes, and nothing depends on it.** The Minutes generation path parses the generated document into summary, discussion, decision, and action buckets by matching heading text. Those buckets are computed and then discarded — only the whole document is displayed and exported. Anchors do not participate in that parsing, and the prompts' headings are not being renamed, so bucket assignment is unaffected either way. This is noted because a future change that begins *using* those buckets would make heading text load-bearing, at which point a check on prompt headings becomes a correctness concern rather than a documentation one.

**No new markdown construct is introduced.** Anchors are plain text inside existing bullets and cells, so the markdown renderer needs no changes.

**Interaction language, not processing language, governs the label.** The switch label is localized like every other control. The anchors themselves are numeric and language-neutral.

## Testing Decisions

**A good test here asserts on what a caller receives, not on how it is produced.** No test should reach into the prompt string and pattern-match a sentence to check the model was told something. Where prompt behaviour matters, the test drives generation through a fake provider and asserts on the document that comes out.

**The export seam is the primary seam.** Export writes into a temporary directory and the resulting file is read back and asserted on — the same file-based shape the suite already uses for headless output. This is the highest point at which the toggle's behaviour is observable: a caller never sees the strip, only its document. Assertions are on the text of the written file and, for Word, on the paragraph and table text read back through the document library.

This closes a gap the last spec named explicitly: the export module's conversion logic currently has no coverage at all. This feature would write the first test that asserts on exported content, which is the right time to close it.

**No seam is added to the strip transform itself.** A pure `strip(text) -> str` helper is the obvious thing to unit-test and the wrong thing to test — it would pin an implementation detail while leaving the real question ("does the toggle produce the right document?") unasked. The transform is covered through the export seam.

**Anchor presence and absence are both asserted at the export seam.** A fixture **Minutes** document with anchors on bullets, on prose, and on table cells, exported with the toggle on and off, asserting both documents. A second fixture with no anchors, asserting the strip is a no-op rather than an error. A third with an item that has no anchor, asserting the strip does not damage it.

**The transform is proven not to damage markdown.** Because stripping runs before the markdown renderers, the tests assert that a stripped table still parses into the same rows and columns, and that bold spans and pipes survive. This is the failure mode most likely to appear and least likely to be noticed by eye.

**Prompts are asserted at the existing prompt seam, structurally.** The suite already asserts every **Template** and **Processing language** yields a prompt containing the transcript placeholder; that test is extended to assert the anchor rule is present in all eight literals, in both languages, without pinning its wording.

**The new setting reuses the session round-trip seam.** The toggle's value survives save and load, and a session written before the setting existed loads with the documented default. These follow the existing pattern for a newly persisted field.

**The toggle label is covered by the existing i18n contract, automatically.** The suite's source-walk asserts every literal translation call in the application resolves in every **Interface language**, so adding the control's labels is checked without a new test.

**The cache version is asserted at the session seam.** A cache entry at the current version is used; an entry at an older version reads as a miss.

**The documentation check is a structural comparison**, consistent with the suite's existing practice of reading a source file and asserting a structural property. It reads the prompts, reads the reference documents, compares heading sets, and asserts a non-vacuous result for each of the four **Templates**.

**Every new test must be registered in the suite's entry point.** The suite runs under a hand-written runner that calls each test by name; an unregistered test silently never runs. The suite already contains a self-guard for this, and new tests must satisfy it.

**The full existing suite must still pass.** The session, i18n, and generation tests in particular assert on the surface this feature touches.

## Out of Scope

- **Clickable anchors.** No anchor jumps to a point in the **Transcript**, and no audio playback. There is no audio player in the application, so a click could at best scroll the transcript text, which needs a marker index in the renderer and a cross-tab scroll API. The requirement is that anchors be visible.
- **Recap and Action items.** Neither document carries **time anchors**, and neither is affected by the toggle.
- **Markdown export.** The Markdown exporter and its unused button label remain unused. The toggle applies to the Word and text exports and to the combined **Export All**.
- **A headless switch.** Headless output carries anchors unconditionally; no command-line flag is added.
- **Anchor validation.** Anchors are written by the model from markers present in the **Transcript**, and are not checked afterwards against the recording. An incorrect anchor is possible and is not corrected.
- **Using the parsed Minutes buckets.** The buckets remain computed and discarded. Nothing begins consuming them.
- **Anchor placement in an export-specific way.** The anchor's position is fixed by the document structure. It is not moved into a margin, a footnote, or a separate column.
- **A single source of truth for prompts and reference documents.** Both copies remain; the reference documents are not turned into the runtime source of the prompts.
- **Backfilling anchors onto existing documents.** Minutes generated before this change are regenerated through the cache version, not retrofitted.
- **Per-Template anchor behaviour.** The toggle does not vary by **Template**, and anchors appear in all four.

## Further Notes

The vocabulary in this spec is defined in the project glossary, where **Time anchor** and an amended **Export** have been added.

Two facts constrain this work and are worth carrying into implementation:

The **Transcript** reaches the synthesis prompt with its markers intact, and nothing between chunk assembly and the prompt strips them. That is why the feature is a prompt change and not a pipeline change.

No architectural decision here is hard to reverse, surprising without context, or the result of a trade-off between genuine alternatives, so no ADR is recorded. The nearest candidate — making the reference documents the source of the prompts — was considered and rejected: the documents mirror only the English half of the prompts, so adopting them as the source would either drop Bahasa Melayu **Minutes** or multiply the documents to maintain. The chosen approach keeps both copies and checks that they agree.

The section buckets parsed from generated minutes are not load-bearing today and are unaffected by this change. If a future feature begins displaying or exporting them individually, the heading keywords in that parser become correctness-critical and the documentation check described above should be extended to cover them.