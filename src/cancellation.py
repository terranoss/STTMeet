"""
STTMeet Cooperative Cancellation

Long blocking steps (audio upload, Files API polling, Gemini generation) must be
able to abandon the run when the user cancels. Python cannot safely kill a running
thread, so cancellation is cooperative: the worker checks the shared event at
every point where it is safe to stop and raises CancelledError.

A blocking network call already in flight cannot be interrupted; the run unwinds
as soon as that call returns.
"""
import time

# Granularity at which a blocking sleep re-checks the cancel event.
CANCEL_POLL_SLICE_SECONDS = 0.2


class CancelledError(RuntimeError):
    """Raised when a long-running operation observes a set cancel event."""


def is_cancelled(cancel_event) -> bool:
    """True when the supplied event (if any) has been raised. None means 'never'."""
    return cancel_event is not None and cancel_event.is_set()


def raise_if_cancelled(cancel_event):
    """Abort the current operation when cancellation was requested."""
    if is_cancelled(cancel_event):
        raise CancelledError("Operation cancelled by user.")


def cancellable_sleep(cancel_event, seconds: float, poll_interval: float = 0.2) -> bool:
    """
    Sleep that reacts to cancellation instead of blocking for the full duration.

    Returns True if the full sleep elapsed, False if it was cut short by a cancel.
    """
    if seconds <= 0:
        return not is_cancelled(cancel_event)

    deadline = time.monotonic() + seconds
    while True:
        if is_cancelled(cancel_event):
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(poll_interval, remaining))