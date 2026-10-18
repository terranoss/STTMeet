# 04: Reference documents match the prompts, and stay matching

**What to build:** Each **Template** has a reference document describing its section structure for developers to read. Those documents currently differ from the prompts in small ways, and nothing notices. This ticket brings them back into agreement and adds a check so a later heading change cannot silently invalidate them.

**Blocked by:** 02 — Anchors in every Template and language, and pre-anchor sessions regenerate.

**Status:** ready-for-agent

- [ ] All four **Template** reference documents describe the section structure the prompts actually produce after the **time anchor** rule is added.
- [ ] The check reads the prompts and the reference documents, compares their section heading sets, and asserts the two agree.
- [ ] Only headings are compared. Full-text comparison would fail on harmless placeholder wording that differs between the copies, so it is not used.
- [ ] The check asserts it found all four **Templates** and a non-trivial heading count for each, so a broken parse cannot produce a silent pass.
- [ ] The check covers the English prompts. There are no Malay reference documents, so that gap is stated rather than papered over.
- [ ] The check is a structural comparison consistent with the suite's existing practice of reading a source file and asserting a structural property.
- [ ] The new test is registered in the suite's entry point, and the full existing suite still passes.

**Note for whoever picks this up:** this protects documentation accuracy only. Buckets parsed from generated **Minutes** are computed and discarded — nothing displays or exports them — so a heading change cannot misfile anything today. If a future feature begins using those buckets, extend this check to cover them at that point.