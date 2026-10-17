"""
STTMeet Gemini Transcriber
Uploads chunked audio to Google Files API via google-genai SDK, polls until ACTIVE,
prompts Gemini with Malay-English Code-Switching guidelines,
and ensures cloud file deletion cleanup.

Retry, backoff, Quota failure detection and failover are owned by the shared
policy in gemini_failover. What stays here is transcription's own concern: the
Diarization policy per model, the transcription prompt, and the uploaded
audio's lifecycle -- which brackets one model's whole retry sweep, is reused
across that model's retries, and is deleted whatever the sweep ended in.
"""
from typing import Optional, Callable, List
from google import genai
from google.genai import types

from .cancellation import CANCEL_POLL_SLICE_SECONDS, CancelledError, cancellable_sleep, raise_if_cancelled
from .config import MODEL_NAME, FALLBACK_MODELS, MAX_OUTPUT_TOKENS, TEMPERATURE
from .gemini_failover import EmptyResponseError, FailoverCall, generate_with_failover
from .logger import get_logger

log = get_logger(__name__)

# Divergence from the text-generation call sites is deliberate and
# user-visible, so it is spelled out here rather than inherited silently.
# Transcription backs off by attempt * 4 seconds on a transient fault, and by
# attempt * 3 seconds on an empty transcription, which is a third thing
# entirely: the provider answered, with nothing.
TRANSCRIPTION_BACKOFF_STEP_SECONDS = 4
TRANSCRIPTION_EMPTY_RETRY_STEP_SECONDS = 3
TRANSCRIPTION_QUOTA_FAILURE_MESSAGE = (
    "All available Gemini models ({models}) exceeded daily free quotas or failed.\n"
    "Please try again later once your Gemini quota resets, or use a different API key."
)
TRANSCRIPTION_ATTEMPT_PROGRESS = "Calling Gemini {model} (Attempt {attempt}/{max_retries})..."
TRANSCRIPTION_RETRY_PROGRESS = "Server notice. Retrying in {seconds}s..."

MALAY_ROJAK_TRANSCRIPTION_PROMPT = """You are an elite speech-to-text transcriber specializing in Malaysian business, government, and technical meetings.
The meeting is conducted primarily in Bahasa Melayu with frequent English code-switching ("Bahasa Rojak").

CRITICAL TRANSCRIPTION RULES:
1. Natural Code-Switching: Transcribe dialogue precisely as spoken. Keep Bahasa Melayu and English terms exactly in the language they were uttered. Do NOT translate speech.
2. Malaysian Particles & Slang: Retain characteristic particles and colloquialisms faithfully (e.g., lah, kan, kot, je, aje, tau, meh, lor, ya, wei, eh, haa).
3. Conversational Normalization: Normalize informal contracted speech into clear, readable words without altering meaning:
   - "tak leh" / "xleh" -> "tak boleh"
   - "camne" -> "macam mana"
   - "dorang" -> "diorang"
   - "kat" -> "dekat"
   - "tengok" (keep as is), "dah" (keep as is)
4. Acronyms & Jargon: Preserve all Malaysian government, business, and tech acronyms accurately (e.g., KPI, SOP, PBT, MOF, KWSP, EPF, SSM, LHDN, HRDF, JKR, IT, AI).
5. Disfluency Cleaning: Omit hesitation fillers ("uhm", "err", "aa", repeated stuttering) while retaining clear spoken statements.
6. {speaker_rule}
7. Timestamps: Insert timestamps at the start of each spoken turn in format [MM:SS] (or [HH:MM:SS] if >1 hr).

{speaker_continuity_context}

OUTPUT FORMAT STRICT REQUIREMENT:
{output_format}

Transcribe every spoken sentence thoroughly. Do not skip sections or provide summaries in this output.
"""

def get_gemini_client(api_key: str) -> genai.Client:
    """Initialize Google GenAI Client with given API key."""
    if not api_key:
        log.error("Gemini API Key is missing.")
        raise ValueError("Gemini API Key is missing. Please set it in Settings or .env file.")
    log.debug("Gemini client initialized.")
    return genai.Client(api_key=api_key)

def _delete_cloud_file(client: genai.Client, uploaded_file) -> None:
    """Best-effort Cloud Storage cleanup; never masks the caller's exception."""
    if uploaded_file is None:
        return
    try:
        client.files.delete(name=uploaded_file.name)
        log.debug("Deleted cloud file: %s", uploaded_file.name)
    except Exception as cleanup_err:
        log.warning("Failed to delete cloud file %s: %s", uploaded_file.name, cleanup_err)


def upload_and_wait_file(
    client: genai.Client,
    file_path: str,
    progress_callback: Optional[Callable[[str], None]] = None,
    poll_interval: int = 4,
    cancel_event=None
) -> types.File:
    """Upload audio file to Google Files API and poll until state is ACTIVE."""
    log.info("Uploading file to Google Files API: %s", file_path)
    raise_if_cancelled(cancel_event)
    if progress_callback:
        progress_callback("Uploading chunk to Google Files API...")

    uploaded_file = client.files.upload(file=file_path)
    log.debug("Upload initiated, file name: %s, state: %s", uploaded_file.name, uploaded_file.state.name)

    try:
        while uploaded_file.state.name == "PROCESSING":
            if progress_callback:
                progress_callback("Waiting for Google Files API audio processing...")
            log.debug("File %s still PROCESSING, polling in %ds...", uploaded_file.name, poll_interval)
            # Sleep in short slices so a cancel is noticed in ~0.2s, not after
            # the full poll interval.
            if not cancellable_sleep(cancel_event, poll_interval, CANCEL_POLL_SLICE_SECONDS):
                raise CancelledError("Upload polling cancelled by user.")
            uploaded_file = client.files.get(name=uploaded_file.name)

        raise_if_cancelled(cancel_event)

        if uploaded_file.state.name != "ACTIVE":
            log.error("Google Files API processing failed. File: %s, State: %s", uploaded_file.name, uploaded_file.state.name)
            raise RuntimeError(f"Google Files API processing failed with state: {uploaded_file.state.name}")
    except CancelledError:
        # The caller only learns about this file if upload_and_wait_file
        # returns, so an abandoned upload has to be released here or it is
        # orphaned in Cloud Storage.
        _delete_cloud_file(client, uploaded_file)
        raise

    log.info("File %s is ACTIVE and ready.", uploaded_file.name)
    if progress_callback:
        progress_callback("Audio processing ready in cloud.")
    return uploaded_file

def transcription_prompt_for_model(
    model_candidate: str,
    previous_tail_transcript: Optional[str] = None,
    diarize: bool = True
) -> str:
    """
    The prompt this chunk is sent to one particular model of the Failover chain.

    Diarization is asked for only of models strong enough to do it, so a weak
    model in the chain is sent a clean-transcription prompt with no speaker
    continuity to keep up.
    """
    # Disable diarization for weak models (e.g. Gemini 3.5 Flash Lite)
    effective_diarize = diarize and ("lite" not in model_candidate.lower())

    if effective_diarize:
        speaker_rule = "Speaker Diarization: Label speakers consistently based on acoustic voice characteristics as 'Speaker 1', 'Speaker 2', etc."
        output_format = "[MM:SS] Speaker X: <Spoken content>\n[MM:SS] Speaker Y: <Spoken content>\n..."
    else:
        speaker_rule = "Clean Transcription: Do NOT guess or label speaker numbers. Transcribe speech naturally with time markers only."
        output_format = "[MM:SS] <Spoken content>\n[MM:SS] <Spoken content>\n..."

    # Build speaker continuity guidance if previous chunk context is available
    if effective_diarize and previous_tail_transcript and previous_tail_transcript.strip():
        continuity_note = f"""
SPEAKER CONTINUITY GUIDANCE:
The immediately preceding segment ended with the following conversation:
---
{previous_tail_transcript.strip()}
---
Maintain the same Speaker numbers (Speaker 1, Speaker 2, etc.) for the corresponding voices.
"""
    else:
        continuity_note = ""

    return MALAY_ROJAK_TRANSCRIPTION_PROMPT.format(
        speaker_rule=speaker_rule,
        output_format=output_format,
        speaker_continuity_context=continuity_note
    )


def extract_transcription(
    response,
    model_candidate: str,
    attempt: int,
    max_retries: int
) -> str:
    """
    Read this chunk's transcript out of a provider response.

    Robust extraction: check response.text first, then candidate content parts.
    A response with nothing usable in it is not a chunk, so it is signalled as
    an empty response and the shared policy retries it on its own backoff.
    """
    text_output = ""
    if response.text and response.text.strip():
        text_output = response.text.strip()
    elif response.candidates:
        extracted_parts = []
        for cand in response.candidates:
            if cand.content and cand.content.parts:
                for part in cand.content.parts:
                    if hasattr(part, "text") and part.text:
                        extracted_parts.append(part.text)
        text_output = "\n".join(extracted_parts).strip()

    if not text_output:
        log.warning(
            "Model '%s' returned empty text on attempt %d/%d (finish_reason: %s).",
            model_candidate, attempt, max_retries,
            getattr(response.candidates[0], "finish_reason", "UNKNOWN") if response.candidates else "NO_CANDIDATES"
        )
        raise EmptyResponseError("The provider returned an empty transcription.")

    return text_output


def transcribe_audio_chunk(
    client: genai.Client,
    chunk_file_path: str,
    previous_tail_transcript: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
    max_retries: int = 3,
    model_override: Optional[str] = None,
    cancel_event=None,
    diarize: bool = True,
    backoff_step: float = TRANSCRIPTION_BACKOFF_STEP_SECONDS,
    empty_retry_step: float = TRANSCRIPTION_EMPTY_RETRY_STEP_SECONDS
) -> str:
    """
    Transcribes a single audio chunk using the configured Gemini model.

    Retry, backoff, Quota failure detection and failover are owned by the
    shared policy in gemini_failover; the Diarization policy, the prompt, and
    the uploaded audio's lifecycle stay here. The uploaded audio brackets one
    model's whole retry sweep, so a retry reuses it rather than uploading
    again, and it is deleted whatever the sweep ended in -- an answer, a
    failure, or a cancellation.

    Pass a threading.Event as cancel_event to make the run abandonable: the
    function raises CancelledError at the first safe checkpoint after the event
    is set, and never returns a partial transcription.
    """
    # Build candidate models list: preferred model first, followed by remaining fallback models
    preferred = model_override or MODEL_NAME
    models_to_try = [preferred] + [m for m in FALLBACK_MODELS if m != preferred]

    log.info("Starting transcription of chunk: %s (models available: %s)", chunk_file_path, models_to_try)

    def upload_this_chunk(model_candidate: str) -> types.File:
        """
        Put this chunk where the provider can hear it.

        This runs before the policy takes ownership of the result, so it is
        also where an upload that never becomes usable -- cancelled mid-poll, or
        refused by the Files API -- has to release itself.
        """
        log.info("Attempting transcription with model: %s", model_candidate)
        return upload_and_wait_file(
            client, chunk_file_path, progress_callback, cancel_event=cancel_event
        )

    def delete_this_chunk(uploaded_file) -> None:
        """Automatic Cloud Storage Cleanup, whatever the sweep ended in."""
        _delete_cloud_file(client, uploaded_file)

    return generate_with_failover(client, FailoverCall(
        description="chunk transcription",
        label="transcription",
        models=models_to_try,
        contents_for_model=lambda model, uploaded_file: [
            # The audio the policy just put there for this model, so every retry
            # of this model sends the same upload rather than paying again.
            uploaded_file,
            transcription_prompt_for_model(model, previous_tail_transcript, diarize),
        ],
        max_retries=max_retries,
        backoff_step=backoff_step,
        temperature=TEMPERATURE,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        final_error=TRANSCRIPTION_QUOTA_FAILURE_MESSAGE.format(models=", ".join(models_to_try)),
        progress_callback=progress_callback,
        attempt_progress=TRANSCRIPTION_ATTEMPT_PROGRESS,
        retry_progress=TRANSCRIPTION_RETRY_PROGRESS,
        extract=lambda response, model, attempt: extract_transcription(
            response, model, attempt, max_retries
        ),
        empty_backoff_step=empty_retry_step,
        cancel_event=cancel_event,
        prepare=upload_this_chunk,
        cleanup=delete_this_chunk,
    ))
