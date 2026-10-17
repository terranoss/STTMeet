# 02: Move Minutes and Action items onto the shared failover policy

**What to build:** The **Minutes** and **Action items** generation paths stop carrying their own copies of the **Failover chain** policy and use the shared one instead. When this ticket lands, all three text-generation paths — minutes, **Action items**, **Recap** — decide failure behaviour in one place, and a maintainer changing that behaviour changes it once.

The differences between these callers are real and deliberate, so they survive as explicit inputs rather than as accidental drift. A user selecting a different **Engine** should see no change in what gets retried or how long it waits — this ticket moves where the decision is made, not what the decision is.

**Blocked by:** 01 — Stand up the shared failover policy with Recap as its first caller

**Status:** ready-for-agent

- [ ] **Minutes** and **Action items** both delegate retry, backoff, **Quota failure** detection and failover to the shared policy
- [ ] Each call site's **Failover chain**, backoff step, temperature and final **Quota failure** message are supplied as inputs, not hardcoded at the call site
- [ ] The **Minutes** **Failover chain** and the transcription **Failover chain** remain distinct — minutes keeps its own default and its own fallbacks
- [ ] No copy of the **Quota failure** predicate remains outside the shared policy
- [ ] The existing suite still passes
- [ ] Tests confirm the two migrated paths behave identically to the **Recap** path under a scripted quota error and a scripted transient error