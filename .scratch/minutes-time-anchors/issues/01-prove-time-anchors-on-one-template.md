# 01: Prove time anchors on one Template

**What to build:** Minutes generated with the action-minutes Template in English end each bullet with a **time anchor** — `(12:34)`, or `(1:12:34)` once the meeting runs past an hour — pointing at the point in the **Transcript** where that content was recorded. The **Minutes** tab shows them. This is the tracer: it establishes that the model complies with the rule, that the markdown renderer handles anchors inside bullets, and that parsing the generated document into its buckets is undisturbed, before the rule is written for every **Template**.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] The English action-minutes prompt instructs the model to close each bullet with a **time anchor**, in parenthesised form, switching to the hour form on the same boundary the **Transcript** uses.
- [ ] The prompt states that an item with nothing to point at carries no anchor at all, rather than a placeholder.
- [ ] Generated **Minutes** display anchors in the **Minutes** tab and the document remains readable with them present.
- [ ] Buckets parsed from the generated document are unchanged in content — anchors appear in the whole document and nowhere else.
- [ ] A test drives generation through the existing fake provider and asserts on the resulting document, not on the prompt's wording.
- [ ] The new test is registered in the suite's entry point so it actually runs.
- [ ] The full existing suite still passes.