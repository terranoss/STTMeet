"""
STTMeet Shared Gemini Failover Policy

One place decides what happens when a model refuses a request. Every Gemini
call site -- transcription, Minutes, Action items, Recap -- used to carry its
own copy of the Failover chain loop: chain iteration, retry, backoff, Quota
failure detection and failover. The copies had already drifted apart, and none
of them had a test, so a change to the policy meant making it four times.

This module owns that policy. It is a sibling of cancellation.py and imports
only cancellation, configuration and logging. It knows how to walk a Failover
chain, when to retry, when to give up on a model and when to stop entirely --
and it can be driven end to end from a test with a fake provider, spending no
quota and making no network call.

What legitimately differs per call site is carried by FailoverCall rather than
baked in here: the contents to send, the Failover chain, the retry count, the
backoff step, the temperature, and the final error message. The divergence
between call sites is deliberate and user-visible, so it is made visible here
instead of being quietly unified.

The module holds no provider-specific policy. A call site that owns a resource
-- the transcriber's uploaded audio -- brackets one model's whole retry sweep
with the prepare/cleanup callbacks and keeps the resource's lifecycle to
itself; this module never learns what the resource is.
"""
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence

from .cancellation import CancelledError, cancellable_sleep, raise_if_cancelled
from .config import MAX_OUTPUT_TOKENS, TEMPERATURE
from .logger import get_logger

log = get_logger(__name__)

# Markers the provider uses when it refuses a request for the day rather than
# for a transient fault. Case-sensitive as the provider sends them; the prose
# marker is matched case-insensitively.
QUOTA_FAILURE_MARKERS = ("429", "RESOURCE_EXHAUSTED")
QUOTA_FAILURE_TEXT = "quota exceeded"

DEFAULT_FINAL_ERROR = (
    "All available Gemini models ({models}) exceeded daily free quotas or failed.\n"
    "Please check your Google AI Studio quota limits or retry tomorrow."
)


def is_quota_failure(error: Exception) -> bool:
    """
    True when the provider is signalling a Quota failure rather than a transient
    fault. A Quota failure ends this model's retry sweep immediately: waiting
    will not bring today's allowance back.
    """
    message = str(error)
    if QUOTA_FAILURE_TEXT in message.lower():
        return True
    return any(marker in message for marker in QUOTA_FAILURE_MARKERS)


@dataclass
class FailoverCall:
    """
    A description of one Gemini request, carrying what varies per call site.

    contents, models and description are required; everything else has a
    default that matches the text-generation call sites.
    """

    description: str
    """What this call is doing, for the log ('recap synthesis')."""

    label: str
    """Short noun for progress text ('recap'), as a user reads it."""

    contents: Sequence[Any]
    """What to send. Opaque here; the policy does not inspect it."""

    models: List[str]
    """The Failover chain: the Engine's choice first, then the fallbacks."""

    max_retries: int = 3
    backoff_step: float = 5
    temperature: float = TEMPERATURE
    max_output_tokens: int = MAX_OUTPUT_TOKENS
    final_error: Optional[str] = None
    progress_callback: Optional[Callable[[str], None]] = None
    cancel_event: Optional[Any] = None
    prepare: Optional[Callable[[str], Any]] = None
    """Called with each model before its retry sweep; returns a resource."""

    cleanup: Optional[Callable[[Any], None]] = None
    """Called with that resource afterwards, whatever the sweep did."""


def _final_message(call: FailoverCall) -> str:
    if call.final_error:
        return call.final_error
    return DEFAULT_FINAL_ERROR.format(models=", ".join(call.models))


def generate_with_failover(client, call: FailoverCall) -> str:
    """
    Make one request, walking the Failover chain until a model answers.

    A Quota failure ends that model's retry sweep at once and moves to the
    next model; anything else retries with backoff until the retry count is
    spent, then moves to the next model. Raises RuntimeError with the call's
    final error message once the whole chain is exhausted, and CancelledError
    when the run is cancelled.
    """
    for model_candidate in call.models:
        raise_if_cancelled(call.cancel_event)
        log.info("Attempting %s with model: %s", call.description, model_candidate)

        resource = call.prepare(model_candidate) if call.prepare else None
        try:
            for attempt in range(1, call.max_retries + 1):
                try:
                    raise_if_cancelled(call.cancel_event)
                    log.info(
                        "Calling Gemini model '%s' for %s (Attempt %d/%d)...",
                        model_candidate, call.description, attempt, call.max_retries
                    )
                    if call.progress_callback:
                        call.progress_callback(
                            f"Generating {call.label} with {model_candidate} "
                            f"(Attempt {attempt}/{call.max_retries})..."
                        )

                    response = client.models.generate_content(
                        model=model_candidate,
                        contents=call.contents,
                        # A plain mapping, not the provider's config object: the
                        # policy speaks in plain data so that no provider type
                        # crosses the seam. The SDK accepts either.
                        config={
                            "max_output_tokens": call.max_output_tokens,
                            "temperature": call.temperature
                        }
                    )
                    # The call cannot be interrupted; discard its result if a
                    # cancel was requested while it was in flight.
                    raise_if_cancelled(call.cancel_event)

                    result = response.text or ""
                    log.info(
                        "%s generated successfully with '%s' (%d chars).",
                        call.description, model_candidate, len(result)
                    )
                    return result

                except CancelledError:
                    # Must precede the generic handler or the cancel would be
                    # treated as a transient failure and retried.
                    raise

                except Exception as e:
                    err_str = str(e)

                    if is_quota_failure(e):
                        log.warning(
                            "Quota exhausted for model '%s' during %s. Triggering automatic failover.",
                            model_candidate, call.description
                        )
                        if call.progress_callback:
                            call.progress_callback(
                                f"Quota reached for {model_candidate}. Auto-switching model..."
                            )
                        break

                    # Temporary 503 or transient network error
                    if attempt < call.max_retries:
                        wait_sec = attempt * call.backoff_step
                        if call.progress_callback:
                            call.progress_callback(
                                f"Server busy. Retrying in {wait_sec}s "
                                f"(Attempt {attempt + 1}/{call.max_retries})..."
                            )
                        if not cancellable_sleep(call.cancel_event, wait_sec):
                            raise CancelledError("Retry backoff cancelled by user.")
                    else:
                        log.error(
                            "All %d %s attempts failed for '%s': %s",
                            call.max_retries, call.description, model_candidate, err_str[:80]
                        )
                        break
        finally:
            if call.cleanup:
                call.cleanup(resource)

    raise RuntimeError(_final_message(call))