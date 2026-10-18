"""
STTMeet Headless Adapter

The second caller on the Pipeline run seam, and the reason the seam is worth having: an
Audio file goes in at a terminal, and a Transcript and Minutes come out on disk, with no
window constructed and no UI toolkit imported.

This is an adapter, so it does two things the Pipeline run deliberately does not. It
decides where the documents land, because writing a Transcript or Minutes to disk is an
Export and Export is a caller's concern. And it renders the run's reports for a reader,
here in English, best effort: a key with no wording behind it still prints, because the
Pipeline run reports translation keys and this path must not need a translation table to
run.
"""
import signal
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .config import get_api_key
from .cancellation import CancelledError
from .i18n import has_key, translate
from .logger import get_logger
from .pipeline import Phase, PipelineResult, PipelineSettings, run_pipeline

log = get_logger(__name__)

EXIT_OK = 0
"""A Transcript and Minutes were both written."""

EXIT_NO_TRANSCRIPT = 1
"""Transcription failed; nothing was written."""

EXIT_NO_MINUTES = 2
"""A Transcript was written; Minutes synthesis failed."""

EXIT_CANCELLED = 130
"""The run was cancelled with Ctrl+C. The Checkpoint survives; nothing was written."""

TRANSCRIPT_SUFFIX = "_transcript.md"
MINUTES_SUFFIX = "_minutes.md"


class ConsoleObserver:
    """
    Prints what the Pipeline run reports, in its own terms.

    Every line names the report's key and the arguments it was given, so the output is
    readable without a translation table. When the English wording happens to be
    available it is printed too, which is a convenience and never a requirement: an
    unknown key still prints.
    """

    def __init__(self, stream=None):
        self.stream = stream if stream is not None else sys.stdout

    def report(self, report) -> None:
        args = " ".join("%s=%s" % (name, value) for name, value in sorted(report.args.items()))
        extras = []
        if report.percent is not None:
            extras.append("%.0f%%" % (report.percent * 100))
        if report.state:
            extras.append(report.state)
        if report.index is not None:
            extras.append("#%s" % report.index)

        line = "[%s] %s" % (report.phase, report.key)
        if extras:
            line += " (%s)" % ", ".join(extras)
        if args:
            line += " " + args

        english = self._english(report)
        if english:
            line += "\n      " + english

        print(line, file=self.stream)

    @staticmethod
    def _english(report) -> str:
        """The English wording for this report, or '' when there is none to give."""
        if report.phase not in (Phase.STATUS, Phase.PROGRESS):
            return ""
        if not has_key(report.key):
            return ""
        try:
            return translate(report.key, "en", **report.args)
        except Exception:
            # A report whose wording needs an argument the table cannot fill is still a
            # report. Printing the key is enough.
            return ""


@dataclass
class HeadlessOutcome:
    """What a headless run produced, and where it put it."""

    exit_code: int
    result: PipelineResult
    transcript_path: Optional[Path] = None
    minutes_path: Optional[Path] = None


@contextmanager
def interrupt_cancels(cancel_event):
    """
    Wire Ctrl+C to a run's cancel event for the duration of the run.

    A terminal user stops a run with Ctrl+C, and the Pipeline run knows how to stop --
    but only through the cancel event it is handed. Translating one into the other is
    this adapter's job, not the pipeline's: the pipeline stays free of signal handling,
    which is also what keeps it usable from a thread or a test.

    The previous handler is put back afterwards, so nothing leaks into the rest of the
    process, and a second Ctrl+C reaches the default handler and stops the terminal
    reader waiting rather than appearing to hang.
    """
    previous = None

    def on_interrupt(signum, frame):
        cancel_event.set()
        # A second Ctrl+C is a reader who has asked twice. Let the default handler end it.
        signal.signal(signal.SIGINT, previous if previous is not None else signal.SIG_DFL)

    try:
        previous = signal.signal(signal.SIGINT, on_interrupt)
    except ValueError:
        # Not the main thread: signals cannot be installed here, and a caller running a
        # Pipeline run on a worker owns cancellation itself.
        yield cancel_event
        return

    try:
        yield cancel_event
    finally:
        signal.signal(signal.SIGINT, previous)


def _write_document(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def run_headless(
    audio_path: str,
    output_dir: Optional[str] = None,
    language: Optional[str] = None,
    engine: Optional[str] = None,
    template: Optional[str] = None,
    preprocess: Optional[bool] = None,
    chunk_minutes: Optional[int] = None,
    cache_dir: Optional[str] = None,
    client: Any = None,
    observer: Any = None,
    cancel_event=None,
    stream=None,
) -> HeadlessOutcome:
    """
    Transcribe one Audio file and write a Transcript and Minutes to disk.

    Anything left as None falls back to the Pipeline run's own defaults, which are what
    the desktop app persists. The API key comes from the environment or .env, since
    there is no interface to read it from. The outcome carries the exit code and where
    the documents landed.

    An interrupted run leaves its Checkpoint where cache_dir says, so restarting the same
    command resumes rather than re-paying for the Chunks already transcribed.
    """
    settings = PipelineSettings(audio_path=str(audio_path), api_key=get_api_key())
    if cache_dir is not None:
        settings.cache_dir = str(cache_dir)
    if language is not None:
        settings.language = language
    if engine is not None:
        settings.engine = engine
    if template is not None:
        settings.template = template
    if preprocess is not None:
        settings.preprocess = preprocess
    if chunk_minutes is not None:
        settings.chunk_minutes = chunk_minutes

    console = ConsoleObserver(stream) if observer is None else observer
    # A cancel_event the caller did not supply is this adapter's to create, and Ctrl+C
    # is wired to it: a terminal reader stopping a run means cancelling it, which leaves
    # the Checkpoint resumable rather than killing the process mid-Chunk.
    cancel_event = cancel_event if cancel_event is not None else threading.Event()
    try:
        with interrupt_cancels(cancel_event):
            result = run_pipeline(settings, console, cancel_event=cancel_event, client=client)
    except CancelledError:
        print(
            "Cancelled. Chunks transcribed so far are in the Checkpoint; "
            "run the same command again to resume.",
            file=sys.stderr,
        )
        return HeadlessOutcome(exit_code=EXIT_CANCELLED, result=PipelineResult())
    except Exception as err:
        # A terminal reader gets a reason and an exit code, not a traceback.
        log.error("Headless Pipeline run failed: %s", err)
        print("Transcription failed: %s" % err, file=sys.stderr)
        return HeadlessOutcome(exit_code=EXIT_NO_TRANSCRIPT, result=PipelineResult())

    audio = Path(settings.audio_path)
    directory = Path(output_dir) if output_dir else audio.parent
    stem = audio.stem

    outcome = HeadlessOutcome(exit_code=EXIT_OK, result=result)
    if not result.transcript.strip():
        print("No transcript was produced; nothing written.", file=sys.stderr)
        outcome.exit_code = EXIT_NO_TRANSCRIPT
        return outcome

    if result.failed_chunks:
        # Writing a partial Transcript under the meeting's own filename would overstate
        # what was heard. The Chunks that did transcribe are banked, so the honest answer
        # is to write nothing and say how to finish the job.
        print(
            "%d of %d Chunks could not be transcribed; nothing written.\n"
            "The Chunks already transcribed are in the Checkpoint -- run the same command "
            "again to resume from here."
            % (result.failed_chunks, result.chunks),
            file=sys.stderr,
        )
        outcome.exit_code = EXIT_NO_TRANSCRIPT
        return outcome

    outcome.transcript_path = _write_document(
        directory / (stem + TRANSCRIPT_SUFFIX), result.transcript
    )
    print("Transcript written to %s" % outcome.transcript_path)

    if result.minutes_error or not result.minutes.strip():
        print(
            "Minutes were not generated: %s" % (result.minutes_error or "empty response"),
            file=sys.stderr,
        )
        outcome.exit_code = EXIT_NO_MINUTES
        return outcome

    outcome.minutes_path = _write_document(directory / (stem + MINUTES_SUFFIX), result.minutes)
    print("Minutes written to %s" % outcome.minutes_path)
    return outcome