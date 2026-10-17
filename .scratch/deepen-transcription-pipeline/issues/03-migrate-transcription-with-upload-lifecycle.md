# 03: Move transcription onto the shared failover policy

**What to build:** The transcription path stops carrying its own copy of the **Failover chain** policy and uses the shared one, keeping its cloud-file upload and cleanup where they belong. Transcription is the one caller with a resource to manage: it uploads audio to the provider, reuses that upload across that model's retries, and deletes it when the model is done with — whether that was success, failure, or cancellation. After this ticket, all four callers decide failure behaviour in one place and none of them leaks provider storage.

A user transcribing a long **Audio file** should keep exactly the resilience they have today. This ticket changes where the decision is made, not what it is — the transcription **Failover chain** stays distinct from the text-generation one, and **Diarization** policy is untouched.

**Blocked by:** 01 — Stand up the shared failover policy with Recap as its first caller

**Status:** ready-for-agent

- [ ] Transcription delegates retry, backoff, **Quota failure** detection and failover to the shared policy
- [ ] The upload lifecycle is expressed as inputs to the shared policy, so the policy itself never learns about uploads
- [ ] One upload brackets that model's whole retry sweep, and is reused across its retries rather than re-uploaded per attempt
- [ ] The uploaded audio is deleted on success, on failure, and on cancellation
- [ ] A cancellation during an upload does not leave the file behind
- [ ] The transcription **Failover chain** and backoff step remain distinct from the text-generation ones
- [ ] **Diarization** policy for weak models is unchanged
- [ ] The existing suite still passes
- [ ] Tests cover upload reuse across retries, cleanup on cancellation, and failover to a later model after a transient error — with no provider call
- [ ] The transcription function's callers are updated, and the change lands as one reviewable diff