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
backoff step, the temperature, how the answer is read out of a response, what
an empty answer means, the progress a user reads, and the final error message.
The divergence between call sites is deliberate and user-visible, so it is made
visible here instead of being quietly unified.

An empty answer is a third kind of outcome, distinct from both an answer and a
fault. A call site that cares says so, by giving an extract callback that can
raise EmptyResponseError and an empty backoff step to retry it on; a call site
that does not care leaves both alone, and an empty answer is an answer.

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

# The progress a user reads while a call is in flight. Wording is per call
# site: the text paths say what they are generating, transcription says which
# model it is calling. Both defaults are the text-generation wording.
DEFAULT_ATTEMPT_PROGRESS = "Generating {label} with {model} (Attempt {attempt}/{max_retries})..."
DEFAULT_RETRY_PROGRESS = (
    "Server busy. Retrying in {seconds}s (Attempt {next_attempt}/{max_retries})..."
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


class EmptyResponseError(Exception):
    """
    Raised by an extract callback to say the provider answered with nothing.

    An empty answer is a third thing, distinct from both a usable answer and a
    fault: the provider replied, and the reply was empty. Transcription treats
    it as its own kind of failure with its own backoff; a call site that has no
    empty_retry_step does not model it and lets the signal escape.
    """


@dataclass
class FailoverCall:
    """
    A description of one Gemini request, carrying what varies per call site.

    description, label and models are required; everything else has a default
    that matches the text-generation call sites.
    """

    description: str
    """What this call is doing, for the log ('recap synthesis')."""

    label: str
    """Short noun for progress text ('recap'), as a user reads it."""

    models: List[str]
    """The Failover chain: the Engine's choice first, then the fallbacks."""

    contents: Sequence[Any] = ()
    """What to send. Opaque here; the policy does not inspect it."""

    contents_for_model: Optional[Callable[[str, Any], Sequence[Any]]] = None
    """
    Built per model, for a chain whose members are sent different things --
    transcription sends a different prompt to a weak model than to a capable
    one, and sends whatever prepare() just handed back. Takes precedence over
    contents when given; the second argument is the prepared resource, or None
    when there is no prepare.
    """

    max_retries: int = 3
    backoff_step: float = 5
    temperature: float = TEMPERATURE
    max_output_tokens: int = MAX_OUTPUT_TOKENS
    final_error: Optional[str] = None
    progress_callback: Optional[Callable[[str], None]] = None
    attempt_progress: str = DEFAULT_ATTEMPT_PROGRESS
    """Wording for 'about to call this model'. Formatted with label, model, attempt, max_retries."""

    retry_progress: str = DEFAULT_RETRY_PROGRESS
    """Wording for 'that failed, backing off'. Formatted with seconds, next_attempt, max_retries."""

    extract: Optional[Callable[[Any, str, int], str]] = None
    """
    Pulls the answer out of a provider response, given the response, the model
    and the 1-based attempt number. Defaults to the response's own text. A call
    site whose answer needs digging for -- or whose empty answer needs to be
    told apart from an answer -- supplies its own.
    """

    empty_backoff_step: Optional[float] = None
    """
    The backoff step for an empty answer, when this call site treats one as a
    failure. None means an empty answer is an answer, and this is what the text
    call sites want.
    """

    cancel_event: Optional[Any] = None
    prepare: Optional[Callable[[str], Any]] = None
    """Called with each model before its retry sweep; returns a resource."""

    cleanup: Optional[Callable[[Any], None]] = None
    """Called with that resource afterwards, whatever the sweep did."""


def _final_message(call: FailoverCall) -> str:
    if call.final_error:
        return call.final_error
    return DEFAULT_FINAL_ERROR.format(models=", ".join(call.models))


def _extract_text(call: FailoverCall, response: Any, model_candidate: str, attempt: int) -> str:
    """The answer this call site reads out of a provider response."""
    if call.extract:
        return call.extract(response, model_candidate, attempt)
    return response.text or ""


def generate_with_failover(client, call: FailoverCall) -> str:
    """
    Make one request, walking the Failover chain until a model answers.

    A Quota failure ends that model's retry sweep at once and moves to the
    next model; anything else retries with backoff until the retry count is
    spent, then moves to the next model. An answer the call site reports as
    empty, if it reports one at all, retries on its own backoff step and then
    gives up on that model the same way. Raises RuntimeError with the call's
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
                            call.attempt_progress.format(
                                label=call.label,
                                model=model_candidate,
                                attempt=attempt,
                                max_retries=call.max_retries,
                            )
                        )

                    response = client.models.generate_content(
                        model=model_candidate,
                        contents=(
                            call.contents_for_model(model_candidate, resource)
                            if call.contents_for_model
                            else call.contents
                        ),
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

                    result = _extract_text(call, response, model_candidate, attempt)
                    log.info(
                        "%s generated successfully with '%s' (%d chars).",
                        call.description, model_candidate, len(result)
                    )
                    return result

                except CancelledError:
                    # Must precede the generic handler or the cancel would be
                    # treated as a transient failure and retried.
                    raise

                except EmptyResponseError:
                    # The provider answered, with nothing. This is not the same
                    # as a fault, so it backs off on its own step.
                    if call.empty_backoff_step is None:
                        # This call site does not model an empty answer, so the
                        # signal is a mistake rather than a policy to apply.
                        raise

                    if attempt < call.max_retries:
                        wait_sec = attempt * call.empty_backoff_step
                        log.warning(
                            "Empty response from '%s' for %s on attempt %d/%d. Retrying in %ds...",
                            model_candidate, call.description, attempt, call.max_retries, wait_sec
                        )
                        if not cancellable_sleep(call.cancel_event, wait_sec):
                            raise CancelledError("Retry backoff cancelled by user.")
                        continue

                    log.error(
                        "Model '%s' returned an empty response on the last of %d %s attempts.",
                        model_candidate, call.max_retries, call.description
                    )
                    break

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
                                call.retry_progress.format(
                                    seconds=wait_sec,
                                    next_attempt=attempt + 1,
                                    max_retries=call.max_retries,
                                )
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