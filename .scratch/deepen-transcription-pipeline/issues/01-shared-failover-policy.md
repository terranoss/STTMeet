# 01: Stand up the shared failover policy with Recap as its first caller

**What to build:** The **Recap** generation path stops carrying its own copy of the **Failover chain** policy and starts using a shared one. Until now, retry, backoff, **Quota failure** detection and failover were written out four times, and the copies had already drifted — different backoff constants, different temperatures, different final messages. After this ticket there is one place that decides what happens when a model refuses a request, and the **Recap** path is the first caller to prove it works.

The point of this ticket is that the policy becomes provable without a provider. A user whose **Quota failure** is handled by the **Recap** path should be getting behaviour that a maintainer can demonstrate from a test suite, with no quota spent and no network call.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] A single module owns **Failover chain** iteration, retry, backoff, **Quota failure** detection and failover
- [ ] That module imports nothing from the generation modules and leaks no provider types across the seam
- [ ] The **Quota failure** predicate exists once, and the **Recap** path uses it
- [ ] A **Quota failure** ends the **Failover chain** immediately instead of retrying
- [ ] A transient error retries with backoff, then fails over to the next model in the chain
- [ ] The **Recap** path's backoff step, temperature and final **Quota failure** message are unchanged from today
- [ ] Tests drive the policy with a scripted fake provider covering quota error, transient error, and success on a later model in the chain
- [ ] No test in the new suite calls the provider
- [ ] The **Recap** generator keeps its own module and its own prompt table
- [ ] The existing suite still passes