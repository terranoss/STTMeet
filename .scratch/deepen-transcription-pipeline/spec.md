Status: ready-for-agent

# Deepen the transcription pipeline, the failover policy, and the translation contract

## Problem Statement

Three things make STTMeet hard to work on, and two of them are defects a user can hit today.

The **pipeline run** — the loop that carries an **Audio file** through preprocessing, **Chunking**, per-**Chunk** transcription, and **Transcript** assembly — exists only as methods on the desktop window. It cannot be run without opening the app, so roughly 577 lines of orchestration have no test coverage at all. Worse, the worker thread reads interface variables from off-thread, which the code's own snapshot mechanism was written to prevent. A user who wants minutes from a recording has no way to get them without sitting in front of the GUI.

The retry and **Failover chain** policy is written out four times: minutes, **Action items**, **Recap**, and transcription. The copies have already drifted apart — three back off one way and one another, text generation pins a different temperature than the transcriber, and the two **Quota failure** messages differ. None of the four has a test. Today a fix to the failure policy means making it four times, and there is nothing to tell a maintainer that all four are supposed to match.

And a user following **Tools → Setup Wizard** with no **Audio file** loaded gets nothing: the menu item silently does nothing. The dialog's title asks the translation table for a key that has never existed. Nothing catches it, because nothing checks that the keys callers pass actually resolve.

## Solution

**A user should be able to run a complete pipeline on a recording from a terminal, and the window should keep working unchanged while it does.**

A user picking a language should never hit a dead menu item — every message the interface asks for should resolve, and the interface should fail loudly in development if one ever does not.

A maintainer changing the **Quota failure** or **Failover chain** behaviour should change it once, in one place, and be able to prove it with a test.

## User Stories

1. As a user with a long **Audio file**, I want to transcribe it and get **Minutes** from a terminal command, so that I can start a run without opening the desktop app.
2. As a user running headless, I want **Transcript** and **Minutes** written to disk on completion, so that I can use them in other tools.
3. As a user running headless, I want to see progress and per-**Chunk** status printed as the run proceeds, so that I know it is alive and how far along it is.
4. As a user running headless, I want to interrupt a run with Ctrl+C and have it stop cleanly, so that I do not leave the machine uploading **Chunks** I no longer want.
5. As a user running headless, I want an interrupted run to resume from its **Checkpoint** when restarted, so that I do not re-pay for **Chunks** already transcribed.
6. As a user running headless, I want the run to honour my **Engine** choice and **Processing language**, so that headless output matches what the app would produce.
7. As a user running headless, I want the same settings the desktop app persists to apply by default, so that the two entry points agree.
8. As a desktop user, I want the window to behave exactly as it does today after this work, so that the refactor costs me nothing.
9. As a desktop user, I want **Transcript** and **Minutes** to appear live in the window while a **Pipeline run** proceeds, so that I keep the **Chunk monitor** and live view I have now.
10. As a desktop user, I want to cancel a **Pipeline run** and have every stage stop promptly, so that cancelling is trustworthy.
11. As a desktop user, I want a failed **Chunk** to stay resumable rather than being marked failed for good, so that retrying picks up where it left off.
12. As a desktop user, I want reprocessing a single failed **Chunk** to behave like the main loop, so that I do not get different results from a retry.
13. As a desktop user, I want my session to save and restore as it does today, so that reopening the app restores my **Transcript** and **Minutes**.
14. As a desktop user, I want saving my session to never touch the interface from the worker thread, so that autosave cannot corrupt the window.
15. As a desktop user, I want settings to be captured once at the start of a **Pipeline run** and reused for the whole run, so that my session saves consistent settings.
16. As a user choosing **Tools → Setup Wizard** with no **Audio file** loaded, I want to be told no file is selected, so that the menu item does not appear dead.
17. As a user choosing **Tools → Setup Wizard** with no **Audio file** loaded, I want the dialog title to be a real translated title, so that it reads as a finished product.
18. As a Malay-speaking user, I want that dialog title translated, so that the interface is consistently in one language.
19. As a maintainer, I want every message the interface asks for to be verified against the translation table in a test, so that a missing key fails the build instead of a user.
20. As a maintainer, I want that check to cover every locale, so that a key present in English but missing in Malay is caught.
21. As a maintainer, I want that check to report the file and line of the offending call, so that I can fix it without searching.
22. As a maintainer, I want the **Failover chain** policy written once, so that **Quota failure** handling cannot drift between call sites.
23. As a maintainer, I want the **Failover chain** policy to be testable without calling the provider, so that I can prove retry and failover behaviour without quota.
24. As a maintainer, I want **Quota failure** to end the **Failover chain** immediately rather than retry, so that a daily quota error fails fast.
25. As a maintainer, I want a transient error to retry with backoff and then fail over to the next model, so that one flaky model does not lose the run.
26. As a maintainer, I want to know the exact backoff for each call site, so that the differences are deliberate and visible rather than accidental.
27. As a maintainer, I want the difference in the **Quota failure** message preserved deliberately, so that this change does not silently alter what users read.
28. As a maintainer, I want transcription's uploaded audio cleaned up whether the run succeeds, fails, or is cancelled, so that provider storage does not leak.
29. As a maintainer, I want the upload cleaned up only after that model's retries are exhausted, so that a retry reuses the upload instead of paying for it again.
30. As a maintainer, I want **Diarization** policy preserved for weak models, so that this change does not alter who gets labelled.
31. As a maintainer, I want the **Recap** generator to keep its own prompts, so that prompt tables for three unrelated documents do not end up in one module.
32. As a maintainer, I want the minutes, **Action items** and **Recap** generation paths unified, so that a bug in the shape of a generation run is fixed once.
33. As a maintainer, I want a failed generation run to always leave the interface in a usable state, so that I cannot end up with controls stuck disabled.
34. As a maintainer, I want the pipeline module to be free of any desktop dependency, so that importing it in a test does not pull in a UI toolkit.
35. As a maintainer, I want the pipeline to take its settings as data rather than reading them, so that the thread-safety leak is closed structurally.
36. As a maintainer, I want the pipeline to report progress as translation keys rather than finished sentences, so that each entry point renders them in its own language.
37. As a maintainer, I want progress reported through one channel rather than several, so that I can add a new consumer without finding every call site.
38. As a maintainer, I want the **Checkpoint** written by the pipeline but the session saved by the caller, so that what a session contains stays the desktop app's decision.
39. As a maintainer, I want **Tail context** handled in one place, so that retries and the main loop cannot disagree about what carries across a **Chunk** seam.
40. As a maintainer, I want the **Overlap** removal applied the same way on a retry as in the main loop, so that reprocessing does not leave duplicated text.
41. As a maintainer, I want the design recorded so a future architecture review does not re-propose extracting this again, so that the reasoning survives.
42. As a maintainer, I want the vocabulary for these concepts written down, so that we stop calling the same thing four different names.

## Implementation Decisions

Three independent pieces of work, landed in the order below. Each is separately reviewable; candidate three is already complete.

### One shared failover policy (do this second)

- A new module, a sibling of the existing cancellation module, owns **Failover chain** iteration, retry, backoff, **Quota failure** detection, and failover. It imports only cancellation, configuration, and logging — no provider types leak across the seam.
- The module exposes one entry point taking a provider client and a description of the call to make. The description carries what legitimately varies per call site: the contents to send, the **Failover chain**, the retry count, the backoff step, the temperature, the final error message, and optional resource-lifecycle callbacks.
- The **Quota failure** predicate — currently written out byte-identically four times — collapses to one function.
- Transcription's cloud-file lifecycle stays in the transcription module. It brackets one model's whole retry sweep and cleans up in a finally block; the text paths have no resource and pass nothing. The generic module never learns about uploads.
- Divergence is preserved, not unified. Backoff step, temperature, and the final **Quota failure** message are parameters. Collapsing them would silently change transcription and text-generation resilience, so they become visible in one place rather than identical.
- The **Recap** generator keeps its own module. After the collapse it holds a prompt table and one call into the shared policy, which is an honest small module rather than a pass-through.
- Known cleanups that fall out: a redundant alias to the action-minutes prompt table, a hardcoded temperature that should read configuration, and two **Prompt** fallback chains whose order disagrees between minutes and the other two.

### A headless-callable pipeline (do this third, after the failover module lands so the call-site change is one clean diff)

- A new module, flat, mirroring the cancellation module's style, owns the **Pipeline run**: the per-**Chunk** loop, resume from **Checkpoint**, **Tail context** carry, **Overlap** removal, per-**Chunk** **Checkpoint** writes, **Transcript** assembly, and cancellation checks.
- The interface is a function taking a settings object, an observer, and a cancellation event. A function rather than a class, because a run's state is passed in and reported out rather than mutated across calls.
- Settings are a plain data object. This is what closes the thread-safety leak: the worker no longer reads an interface variable off-thread because there is no interface variable to read.
- The observer receives a phase, an optional percentage, a translation key, and formatting arguments. Finished sentences are never passed across the seam, so the pipeline carries no locale and a headless caller needs no translation table to run.
- One reporting method covers step badges, status text, progress percentage, and **Chunk** rows, distinguished by phase. This replaces six incompatible callback shapes and the direct calls that bypassed them.
- **Checkpoint** writing moves in. Session saving does not — what constitutes a session is the desktop app's concern, and the pipeline should not know the session schema.
- Reprocessing a single **Chunk** becomes a second entry on the same interface rather than a second copy of the loop. The duplicated **Tail context** idiom disappears with it.
- The three independent generation triggers — minutes, **Recap**, **Action items** — unify into one templated method. The two that are already line-for-line isomorphic collapse; minutes, which differs because it is also reachable from the main run, joins them. The unified version always restores interface state on the way out, including on the path where minutes currently does not.
- Two adapters sit on the seam from the start: the desktop window, and a headless flag on the existing entry point. The second adapter is why the seam is worth having — one adapter alone would be a hypothetical seam.
- The pipeline module must not import anything from the desktop UI package. If a future change needs the **Chunk monitor**, the answer is to report an event and let the adapter render it.

### The translation contract (already complete)

- The dialog title key is corrected to the one the rest of the interface already uses for informational dialogs.
- A test parses the source tree and asserts every literal key passed to the translation functions resolves in every locale, reporting file and line on failure. Parsed rather than pattern-matched, so it survives either quote style and keys built inside f-strings.
- The test guards itself: it asserts it found a floor number of call sites, so a broken walk cannot pass vacuously.
- Only literal arguments are checked. Roughly twenty call sites build their key at runtime; those are already covered by key-existence assertions elsewhere in the suite.
- The test scans source only, not the test suite, which contains a deliberate unknown key used to prove the lookup raises.

## Testing Decisions

A good test here exercises a module's own interface from outside and asserts only on what a caller can observe. It does not reach into private helpers, does not assert on source text formatting, and does not construct a GUI.

One seam per candidate, and the highest available in each case:

- **Pipeline run** — tested at `run_pipeline` with a recording observer and a fake transcription client. This is the highest seam that can still exercise resume, cancellation, and **Transcript** assembly. Tests live in the pipeline module's own terms: they assert what the observer recorded and what came back, never what a widget shows.
- **Failover chain** — tested at the shared failover entry point with a fake provider that can be scripted to fail in specific ways: quota error, transient error, empty response. This is the only seam where the policy can be proven without spending quota.
- **Translation contract** — tested against the lookup function's own guarantee, driven by a parse of the source tree rather than by importing a UI module.

Prior art in the repository, which these follow:

- The existing suite already tests the pure modules through their real interfaces with real temporary directories and no mocking of the module under test. The new tests match that.
- The WCAG contrast-ratio test is the deepest existing test — it asserts a property of data rather than the presence of a call. The placeholder-consistency shape of the new translation test follows it.
- The existing source-text scan for corner radii sets the precedent for a test that reads source, though the new tests prefer parsing.

Test coverage gaps that this work deliberately leaves in place, and that a reviewer should not mistake for oversights: the export module's conversion logic, the theme constants beyond the contrast pairs, and the documentation reader's rendering. None are touched here.

## Out of Scope

- Deleting the dead Markdown export function and the seventeen translation keys orphaned by earlier redesigns. The audit found them; this work does not act on them.
- The hardcoded English in the plain-text export header and the status-bar prefixes for **Recap** and **Action items**.
- Changing **Diarization** policy for weak models, or changing what any **Engine** choice resolves to.
- The storage ownership problem, where clearing a meeting's cache also deletes the user's stored preferences. It is a real defect and a separate spec.
- Moving the documentation parsers out of the UI package so the four-template list has a single owner.
- Any user-facing change to **Templates**, **Minutes** structure, or prompt content.
- Consolidating the settings and session persistence modules behind a shared storage interface.

## Further Notes

The third piece of work is already implemented and the suite passes. The specification describes all three so the record is complete.

Two things a reviewer should know before starting:

The pipeline change is by far the largest of the three — around 577 lines moving out of a 3400-line file, plus a headless adapter, plus the generation-trigger unification. It will likely want splitting into two or three commits even though it stays one piece of work.

The failover module lands first deliberately. It changes the transcription function's signature, and doing that in the same change as the extraction would turn one reviewable diff into an interleaved one.

The vocabulary this spec uses is defined in the project glossary, and the two architectural decisions are recorded as ADRs. Both should be read before starting.