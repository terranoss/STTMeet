"""
STTMeet Gemini Transcriber
Uploads chunked audio to Google Files API via google-genai SDK, polls until ACTIVE,
prompts Gemini with Malay-English Code-Switching guidelines,
and ensures cloud file deletion cleanup.
"""
import time
from typing import Optional, Callable, List
from google import genai
from google.genai import types

from .config import MODEL_NAME, FALLBACK_MODELS, MAX_OUTPUT_TOKENS, TEMPERATURE
from .logger import get_logger

log = get_logger(__name__)

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
6. Speaker Diarization: Label speakers consistently based on acoustic voice characteristics as "Speaker 1", "Speaker 2", etc.
7. Timestamps: Insert timestamps at the start of each speaker turn in format [MM:SS] (or [HH:MM:SS] if >1 hr).

{speaker_continuity_context}

OUTPUT FORMAT STRICT REQUIREMENT:
[MM:SS] Speaker X: <Spoken content>
[MM:SS] Speaker Y: <Spoken content>
...

Transcribe every spoken sentence thoroughly. Do not skip sections or provide summaries in this output.
"""

def get_gemini_client(api_key: str) -> genai.Client:
    """Initialize Google GenAI Client with given API key."""
    if not api_key:
        log.error("Gemini API Key is missing.")
        raise ValueError("Gemini API Key is missing. Please set it in Settings or .env file.")
    log.debug("Gemini client initialized.")
    return genai.Client(api_key=api_key)

def upload_and_wait_file(
    client: genai.Client,
    file_path: str,
    progress_callback: Optional[Callable[[str], None]] = None,
    poll_interval: int = 4
) -> types.File:
    """Upload audio file to Google Files API and poll until state is ACTIVE."""
    log.info("Uploading file to Google Files API: %s", file_path)
    if progress_callback:
        progress_callback("Uploading chunk to Google Files API...")

    uploaded_file = client.files.upload(file=file_path)
    log.debug("Upload initiated, file name: %s, state: %s", uploaded_file.name, uploaded_file.state.name)

    while uploaded_file.state.name == "PROCESSING":
        if progress_callback:
            progress_callback("Waiting for Google Files API audio processing...")
        log.debug("File %s still PROCESSING, polling in %ds...", uploaded_file.name, poll_interval)
        time.sleep(poll_interval)
        uploaded_file = client.files.get(name=uploaded_file.name)

    if uploaded_file.state.name != "ACTIVE":
        log.error("Google Files API processing failed. File: %s, State: %s", uploaded_file.name, uploaded_file.state.name)
        raise RuntimeError(f"Google Files API processing failed with state: {uploaded_file.state.name}")

    log.info("File %s is ACTIVE and ready.", uploaded_file.name)
    if progress_callback:
        progress_callback("Audio processing ready in cloud.")
    return uploaded_file

def transcribe_audio_chunk(
    client: genai.Client,
    chunk_file_path: str,
    previous_tail_transcript: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
    max_retries: int = 3,
    model_override: Optional[str] = None
) -> str:
    """
    Transcribes a single audio chunk using the configured Gemini model.
    Includes exponential backoff retry and automatically deletes the uploaded file when complete.
    Detects model deprecation/unavailability errors and raises a clear message.
    """
    uploaded_file = None

    # Build speaker continuity guidance if previous chunk context is available
    if previous_tail_transcript and previous_tail_transcript.strip():
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

    formatted_prompt = MALAY_ROJAK_TRANSCRIPTION_PROMPT.format(
        speaker_continuity_context=continuity_note
    )

    # Build candidate models list: preferred model first, followed by remaining fallback models
    preferred = model_override or MODEL_NAME
    models_to_try = [preferred] + [m for m in FALLBACK_MODELS if m != preferred]

    log.info("Starting transcription of chunk: %s (models available: %s)", chunk_file_path, models_to_try)

    for model_candidate in models_to_try:
        log.info("Attempting transcription with model: %s", model_candidate)
        uploaded_file = None

        try:
            uploaded_file = upload_and_wait_file(client, chunk_file_path, progress_callback)

            for attempt in range(1, max_retries + 1):
                try:
                    if progress_callback:
                        progress_callback(f"Calling Gemini {model_candidate} (Attempt {attempt}/{max_retries})...")

                    response = client.models.generate_content(
                        model=model_candidate,
                        contents=[
                            uploaded_file,
                            formatted_prompt
                        ],
                        config=types.GenerateContentConfig(
                            max_output_tokens=MAX_OUTPUT_TOKENS,
                            temperature=TEMPERATURE
                        )
                    )

                    # Robust text extraction: check response.text first, then candidate content parts
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
                        if attempt < max_retries:
                            wait_sec = attempt * 3
                            time.sleep(wait_sec)
                            continue
                        else:
                            raise RuntimeError(f"Model {model_candidate} returned empty transcription.")

                    log.info("Chunk transcribed successfully with '%s' (%d chars).", model_candidate, len(text_output))
                    return text_output

                except Exception as api_err:
                    err_str = str(api_err)

                    # Check for 429 quota exhaustion specifically
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota exceeded" in err_str.lower():
                        log.warning(
                            "Quota exhausted for model '%s'. Triggering automatic failover to next model.",
                            model_candidate
                        )
                        if progress_callback:
                            progress_callback(f"Quota reached for {model_candidate}. Auto-switching model...")
                        # Break inner retry loop to try the next model candidate immediately!
                        break

                    # Temporary 503 or transient network errors -> retry with backoff
                    if attempt < max_retries:
                        wait_sec = attempt * 4
                        log.warning("Attempt %d/%d on '%s' failed: %s. Retrying in %ds...", attempt, max_retries, err_str[:80], wait_sec)
                        if progress_callback:
                            progress_callback(f"Server notice. Retrying in {wait_sec}s...")
                        time.sleep(wait_sec)
                    else:
                        log.error("All %d attempts failed for model '%s': %s", max_retries, model_candidate, err_str[:80])
                        # If this model exhausted all retries, fall over to next candidate
                        break

        finally:
            # Automatic Cloud Storage Cleanup
            if uploaded_file is not None:
                try:
                    client.files.delete(name=uploaded_file.name)
                    log.debug("Deleted cloud file: %s", uploaded_file.name)
                except Exception as cleanup_err:
                    log.warning("Failed to delete cloud file %s: %s", uploaded_file.name, cleanup_err)

    raise RuntimeError(
        f"All available Gemini models ({', '.join(models_to_try)}) exceeded daily free quotas or failed.\n"
        "Please try again later once your Gemini quota resets, or use a different API key."
    )
