"""
STTMeet Pipeline Run

One complete pass over a single Audio file: Preprocessing, transcription, Transcript
assembly and Minutes synthesis. This is the orchestration that used to live only as
methods on the desktop window, extracted so that two callers -- the window and a
terminal -- can share it.

Three properties of this module are the point of it, not decoration:

* **It takes its settings as data.** PipelineSettings is a plain dataclass and every
  value the run needs is passed in. Nothing here reads an interface variable, which is
  what closes the thread-safety leak structurally: the worker thread has no widget to
  reach for. See ADR 0001.

* **It reports translation keys, never sentences.** Every report carries a key and
  formatting arguments; the caller renders them in its own language. This module holds
  no locale, so a headless caller needs no translation table to run, and a test asserts
  on keys rather than on English wording.

* **It imports no UI toolkit.** Nothing from src/ui/ may be imported here. If a change
  ever seems to need the Chunk monitor or the transcript view, the answer is to report
  an event and let the adapter render it.

Scope: this is the unchunked path. An Audio file with Chunking off is one Chunk from
end to end. Chunking, resume from Checkpoint, Tail context and Overlap removal arrive
with the next ticket, which fills in the loop this module is shaped to hold.
"""
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional

from .audio_processor import compute_file_hash, preprocess_audio
from .cancellation import CancelledError, raise_if_cancelled
from .gemini_transcriber import get_gemini_client, transcribe_audio_chunk
from .logger import get_logger
from .minutes_generator import generate_meeting_minutes
from .session_store import DEFAULT_SETTINGS

log = get_logger(__name__)

# The four steps of a Pipeline run, as the desktop window badges them.
STEP_PREPROCESS = "step1"
STEP_CHUNKING = "step2"
STEP_TRANSCRIBE = "step3"
STEP_MINUTES = "step4"

# Where the progress bar is at each phase of a Pipeline run. These match the desktop
# window's own fractions so the two agree on where a run is; Chunking and resume will
# subdivide the transcription span.
PREPROCESS_START = 0.0
TRANSCRIBE_START = 0.2
TRANSCRIBE_DONE = 0.8
MINUTES_START = 0.85
COMPLETE = 1.0

# The Engine choices the desktop app persists, mapped to the model that leads the
# Failover chain. Auto-failover pins nothing, which is the absent entry.
ENGINE_MODEL_OVERRIDES = {
    "☁️ Gemini 3.8 Flash": "gemini-3.8-flash",
    "☁️ Gemini 3.5 Flash": "gemini-3.5-flash",
    "☁️ Gemini 3.5 Flash Lite": "gemini-3.5-flash-lite",
}


class Phase:
    """
    What a report is about. One channel carries all four kinds and the phase is what
    tells them apart, so a new kind of report never means a new callback to find.
    """

    STEP = "step"
    """A step badge: key is a step id, state is pending/working/done/error."""

    STATUS = "status"
    """A line of status text: key is a translation key, args are its formatting args."""

    PROGRESS = "progress"
    """Status text that also moves the bar: carries a percentage from 0.0 to 1.0."""

    CHUNK = "chunk"
    """One Chunk's row: key names the Chunk's state and index says which Chunk."""


@dataclass(frozen=True)
class PipelineReport:
    """
    One thing the Pipeline run is doing, said in a form any caller can render.

    Nothing here is a finished sentence. For a STATUS or PROGRESS report, `key` is a
    translation key and `args` are the values to format into it. For a STEP report,
    `key` is a step id and `state` is its badge state. For a CHUNK report, `key` names
    the Chunk's state.
    """

    phase: str
    key: str
    percent: Optional[float] = None
    state: str = ""
    index: Optional[int] = None
    args: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class PipelineSettings:
    """
    Everything one Pipeline run needs, as data.

    The defaults are what the desktop app persists, read from session_store rather than
    copied, so the two entry points cannot drift apart. Two deliberate exceptions: the
    API key is empty, because a headless run reads it from the environment instead, and
    Chunking is off because that is the only path this run supports yet.
    """

    audio_path: str
    api_key: str = ""

    engine: str = DEFAULT_SETTINGS["engine"]
    """Which model leads the Failover chain, for transcription and for Minutes alike."""

    language: str = DEFAULT_SETTINGS["language"]
    """The Processing language the Minutes are written in."""

    template: str = DEFAULT_SETTINGS["template"]
    """The Template the Minutes take."""

    preprocess: bool = DEFAULT_SETTINGS["preprocess"]
    chunk_minutes: int = 0
    """0 means Chunking is off: the whole recording is one Chunk."""


@dataclass
class PipelineResult:
    """What one Pipeline run produced."""

    transcript: str = ""
    minutes: str = ""
    minutes_error: str = ""
    """Set when Minutes synthesis failed. A Minutes failure never costs the Transcript."""

    file_hash: str = ""
    chunks: int = 1
    completed_chunks: int = 0
    engine: Optional[str] = None
    """The model the Engine pinned, or None for auto-failover."""


def model_for_engine(engine: str) -> Optional[str]:
    """
    The model the Engine choice leads the Failover chain with, or None when the choice
    pins nothing (auto-failover).
    """
    if not engine:
        return None
    return ENGINE_MODEL_OVERRIDES.get(engine)


def engine_for_model(model: str) -> str:
    """
    The Engine choice that pins this model, for a caller that was handed a model name
    rather than the choice a person picks -- a command line, say.
    """
    for choice, pinned in ENGINE_MODEL_OVERRIDES.items():
        if pinned == model:
            return choice
    return DEFAULT_SETTINGS["engine"]


def _reports_to(observer):
    """The report function for this run; a caller with nothing to report to gets a sink."""
    if observer is None:
        return lambda report: None
    return observer.report


def run_pipeline(
    settings: PipelineSettings,
    observer: Any = None,
    cancel_event=None,
    client: Any = None,
) -> PipelineResult:
    """
    Run one Pipeline run over a single Audio file, and report what it is doing.

    The whole contract with the caller is settings in, PipelineResult out, and reports
    along the way. Pass a threading.Event as cancel_event to make the run abandonable;
    it raises CancelledError at the first safe checkpoint and never returns a partial
    Transcript. Pass a client to use one that is already built, which is how a test
    drives a whole run without a network call.

    A Minutes failure is caught and handed back in PipelineResult.minutes_error rather
    than raised: the Transcript is worth more than the Minutes, and losing it to a bad
    synthesis would be the expensive way to learn that.
    """
    report = _reports_to(observer)
    result = PipelineResult(file_hash=compute_file_hash(settings.audio_path))

    raise_if_cancelled(cancel_event)
    if client is None:
        client = get_gemini_client(settings.api_key)

    model_override = model_for_engine(settings.engine)
    result.engine = model_override

    # --- Step 1: Preprocessing -------------------------------------------
    report(PipelineReport(phase=Phase.STEP, key=STEP_PREPROCESS, state="working"))
    target_audio = settings.audio_path
    if settings.preprocess:
        report(PipelineReport(phase=Phase.PROGRESS, key="status.step1_start",
                              percent=PREPROCESS_START))
        target_audio = preprocess_audio(
            settings.audio_path,
            progress_callback=lambda message: report(
                PipelineReport(phase=Phase.STATUS, key="status.step1_detail",
                               args={"detail": message})
            ),
        )
    else:
        report(PipelineReport(phase=Phase.STATUS, key="status.step1_done"))
    report(PipelineReport(phase=Phase.STEP, key=STEP_PREPROCESS, state="done",
                          args={"skipped": not settings.preprocess}))
    raise_if_cancelled(cancel_event)

    # --- Step 2: Chunking --------------------------------------------------
    # With Chunking off the whole recording is one Chunk, so this step does no work. The
    # next ticket replaces it with a real split and a loop over what it returns.
    report(PipelineReport(phase=Phase.STEP, key=STEP_CHUNKING, state="working"))
    report(PipelineReport(phase=Phase.STATUS, key="status.step2_off"))
    report(PipelineReport(phase=Phase.STEP, key=STEP_CHUNKING, state="done",
                          args={"skipped": True, "chunk_count": 1}))
    raise_if_cancelled(cancel_event)

    # --- Step 3: Transcribe -------------------------------------------------
    report(PipelineReport(phase=Phase.STEP, key=STEP_TRANSCRIBE, state="working"))
    report(PipelineReport(phase=Phase.PROGRESS, key="status.step3_chunk",
                          percent=TRANSCRIBE_START, args={"index": 1, "total": 1}))
    if model_override:
        report(PipelineReport(phase=Phase.STATUS, key="status.step3_engine",
                              args={"engine": model_override}))
    else:
        report(PipelineReport(phase=Phase.STATUS, key="status.step3_engine_auto"))

    transcript = _transcribe_the_recording(
        replace(settings, audio_path=target_audio), client, model_override, cancel_event, report
    )
    result.transcript = transcript
    result.completed_chunks = 1
    report(PipelineReport(phase=Phase.PROGRESS, key="status.transcript_ready",
                          percent=TRANSCRIBE_DONE, args={"chars": len(transcript)}))
    report(PipelineReport(phase=Phase.STEP, key=STEP_TRANSCRIBE, state="done"))

    # --- Step 4: Minutes ------------------------------------------------------
    report(PipelineReport(phase=Phase.STEP, key=STEP_MINUTES, state="working"))
    report(PipelineReport(phase=Phase.PROGRESS, key="status.step4_start",
                          percent=MINUTES_START, args={"language": settings.language}))
    try:
        result.minutes = generate_meeting_minutes(
            client=client,
            full_transcript=transcript,
            language=settings.language,
            template=settings.template,
            progress_callback=lambda message: report(
                PipelineReport(phase=Phase.STATUS, key="status.step4_detail",
                               args={"detail": message})
            ),
            model_override=model_override,
            cancel_event=cancel_event,
        )
        report(PipelineReport(phase=Phase.PROGRESS, key="status.all_complete",
                              percent=COMPLETE))
        report(PipelineReport(phase=Phase.STEP, key=STEP_MINUTES, state="done"))
    except CancelledError:
        report(PipelineReport(phase=Phase.STEP, key=STEP_MINUTES, state="pending"))
        raise
    except Exception as err:
        # The Transcript is already in hand: say what failed and hand it back anyway.
        log.warning("Minutes synthesis failed, transcript protected: %s", err)
        result.minutes_error = str(err)
        report(PipelineReport(phase=Phase.PROGRESS, key="status.minutes_failed",
                              percent=TRANSCRIBE_DONE))
        report(PipelineReport(phase=Phase.STEP, key=STEP_MINUTES, state="error"))

    return result


def _transcribe_the_recording(
    settings: PipelineSettings,
    client: Any,
    model_override: Optional[str],
    cancel_event,
    report,
) -> str:
    """
    Transcribe the whole recording as the one Chunk a Chunking-off run has.

    Timestamp adjustment, Overlap removal and the per-Chunk Checkpoint write belong to
    the loop the next ticket adds, where there is more than one Chunk for them to matter
    between. They are deliberately not faked here.
    """
    index = 0
    report(PipelineReport(phase=Phase.CHUNK, key="chunk.working", index=index))
    try:
        text = transcribe_audio_chunk(
            client=client,
            chunk_file_path=settings.audio_path,
            progress_callback=lambda message: report(
                PipelineReport(phase=Phase.STATUS, key="status.step3_detail",
                               args={"detail": message})
            ),
            model_override=model_override,
            cancel_event=cancel_event,
        )
    except CancelledError:
        report(PipelineReport(phase=Phase.CHUNK, key="chunk.cancelled", index=index))
        raise
    except Exception as err:
        report(PipelineReport(phase=Phase.CHUNK, key="chunk.error", index=index,
                              args={"error": str(err)}))
        raise
    report(PipelineReport(phase=Phase.CHUNK, key="chunk.done", index=index))
    return text
