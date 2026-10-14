"""
STTMeet Minutes Generator
Generates Executive Summary, Discussion Points, Decisions Made,
Action Items Table, and Formal Meeting Minutes (Minit Mesyuarat) using Gemini.
Supports Bahasa Melayu, English, and Bilingual modes.
"""
from typing import Dict, Any, Callable, Optional, List
from google import genai
from google.genai import types

from .config import MODEL_NAME, FALLBACK_MODELS, MINUTES_MODEL_NAME, MINUTES_FALLBACK_MODELS, MAX_OUTPUT_TOKENS
from .logger import get_logger

log = get_logger(__name__)

MINUTES_SYNTHESIS_PROMPTS = {
    "Bahasa Melayu": """Anda adalah setiausaha mesyuarat korporat dan kerajaan Malaysia yang profesional.
Berdasarkan transkrip mesyuarat di bawah, hasilkan dokumentasi mesyuarat rasmi dalam Bahasa Melayu standard mengikut format Minit Mesyuarat yang teratur.

Sila hasilkan 4 bahagian berasingan dengan tajuk seperti berikut:

### BAHAGIAN 1: RINGKASAN EKSEKUTIF (EXECUTIVE SUMMARY)
- 3 hingga 5 perenggan padat menerangkan tujuan mesyuarat, latar belakang perbincangan, dan hasil keseluruhan.

### BAHAGIAN 2: PERKARA-PERKARA UTAMA YANG DIBINCANGKAN (DISCUSSION HIGHLIGHTS)
- Pecahkan mengikut topik atau agenda perbincangan.
- Nyatakan pandangan utama, isu yang dibangkitkan, dan hujah yang dikemukakan.

### BAHAGIAN 3: KEPUTUSAN MESYUARAT (KEY DECISIONS)
- Senarai bernombor bagi setiap ketetapan atau keputusan rasmi yang telah dipersetujui sebulat suara atau diputuskan oleh pengerusi.

### BAHAGIAN 4: SENARAI TINDAKAN (ACTION ITEMS MATRIX)
Sediakan jadual Markdown lengkap:
| Bil | Tindakan / Tugasan | Pegawai Bertanggungjawab (PIC) | Tarikh Akhir (Deadline) | Status |
|---|---|---|---|---|
(Senaraikan setiap tugasan yang dipersetujui dengan jelas)

### BAHAGIAN 5: HAL-HAL LAIN (OTHER MATTERS)
- Perkara berbangkit atau hal-hal sampingan (AOB) jika ada.

TRANSKRIP MESYUARAT:
{transcript}
""",

    "English": """You are an executive meeting secretary.
Based on the meeting transcript below, generate comprehensive, professional corporate meeting minutes in English.

Please produce 4 distinct sections with the following headings:

### SECTION 1: EXECUTIVE SUMMARY
- 3 to 5 concise paragraphs covering the meeting purpose, key topics, and overarching conclusions.

### SECTION 2: DISCUSSION HIGHLIGHTS
- Grouped by agenda item or topic.
- Note perspectives shared, challenges highlighted, and arguments made.

### SECTION 3: KEY DECISIONS
- Numbered list of all official decisions and agreements reached.

### SECTION 4: ACTION ITEMS MATRIX
Provide a complete Markdown table:
| No | Action Item / Task | Person in Charge (PIC) | Deadline | Status |
|---|---|---|---|---|
(Extract all concrete commitments and tasks)

### SECTION 5: ANY OTHER BUSINESS (AOB)
- Secondary matters or announcements raised.

TRANSCRIPT:
{transcript}
""",

    "Bilingual": """Anda adalah setiausaha mesyuarat profesional.
Berdasarkan transkrip mesyuarat di bawah, hasilkan dokumentasi mesyuarat dwibahasa (Bahasa Melayu & English) dengan tajuk dwi-bahasa.

### 1. RINGKASAN EKSEKUTIF / EXECUTIVE SUMMARY
- 3-5 perenggan merangkumi tujuan dan intipati mesyuarat.

### 2. PERKARA DIBINCANGKAN / DISCUSSION HIGHLIGHTS
- Mengikut topik perbincangan utama.

### 3. KEPUTUSAN MESYUARAT / KEY DECISIONS
- Senarai bernombor keputusan yang dicapai.

### 4. MATRIKS TINDAKAN / ACTION ITEMS MATRIX
Format jadual Markdown:
| Bil / No | Tindakan / Action Item | PIC | Tarikh Akhir / Deadline | Status |
|---|---|---|---|---|

### 5. HAL-HAL LAIN / OTHER MATTERS

TRANSKRIP:
{transcript}
"""
}

import time

def generate_meeting_minutes(
    client: genai.Client,
    full_transcript: str,
    language: str = "Bahasa Melayu",
    progress_callback: Optional[Callable[[str], None]] = None,
    max_retries: int = 3,
    model_override: Optional[str] = None
) -> str:
    """
    Synthesize meeting transcript into summary, decisions, and action items.
    Includes automatic retry with exponential backoff for temporary 503 spikes.
    """
    log.info("Generating meeting minutes in language: %s (transcript length: %d chars)", language, len(full_transcript))
    if progress_callback:
        progress_callback(f"Generating meeting minutes and action items in {language}...")

    prompt_template = MINUTES_SYNTHESIS_PROMPTS.get(language, MINUTES_SYNTHESIS_PROMPTS["Bahasa Melayu"])
    full_prompt = prompt_template.format(transcript=full_transcript)

    preferred = model_override or MINUTES_MODEL_NAME
    models_to_try = [preferred] + [m for m in MINUTES_FALLBACK_MODELS if m != preferred]

    for model_candidate in models_to_try:
        log.info("Attempting minutes generation with model: %s", model_candidate)

        for attempt in range(1, max_retries + 1):
            try:
                log.info("Calling Gemini model '%s' for minutes synthesis (Attempt %d/%d)...", model_candidate, attempt, max_retries)
                if progress_callback:
                    progress_callback(f"Generating minutes with {model_candidate} (Attempt {attempt}/{max_retries})...")

                response = client.models.generate_content(
                    model=model_candidate,
                    contents=[full_prompt],
                    config=types.GenerateContentConfig(
                        max_output_tokens=MAX_OUTPUT_TOKENS,
                        temperature=0.2
                    )
                )
                result = response.text or ""
                log.info("Meeting minutes generated successfully with '%s' (%d chars).", model_candidate, len(result))
                return result

            except Exception as e:
                err_str = str(e)

                # Check for 429 quota exhaustion specifically
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota exceeded" in err_str.lower():
                    log.warning(
                        "Quota exhausted for model '%s' during minutes synthesis. Triggering automatic failover.",
                        model_candidate
                    )
                    if progress_callback:
                        progress_callback(f"Quota reached for {model_candidate}. Auto-switching model...")
                    break  # Try next model candidate immediately!

                # Temporary 503 or transient network error
                if attempt < max_retries:
                    wait_sec = attempt * 5
                    if progress_callback:
                        progress_callback(f"Server busy. Retrying in {wait_sec}s (Attempt {attempt + 1}/{max_retries})...")
                    time.sleep(wait_sec)
                else:
                    log.error("All %d minutes synthesis attempts failed for '%s': %s", max_retries, model_candidate, err_str[:80])
                    break

    raise RuntimeError(
        f"All available Gemini models ({', '.join(models_to_try)}) exceeded daily free quotas or failed.\n"
        "Please check your Google AI Studio quota limits or retry tomorrow."
    )

def parse_minutes_sections(minutes_text: str) -> Dict[str, str]:
    """
    Helper to extract individual sections (Summary, Decisions, Action Items)
    from generated minutes markdown.
    """
    sections = {
        "summary": "",
        "highlights": "",
        "decisions": "",
        "action_items": "",
        "full_text": minutes_text
    }

    current_sec = None
    buffer = []

    for line in minutes_text.splitlines():
        lower = line.lower()
        if "ringkasan eksekutif" in lower or "executive summary" in lower:
            if current_sec and buffer:
                sections[current_sec] = "\n".join(buffer).strip()
            current_sec = "summary"
            buffer = []
        elif "perkara" in lower or "discussion highlights" in lower:
            if current_sec and buffer:
                sections[current_sec] = "\n".join(buffer).strip()
            current_sec = "highlights"
            buffer = []
        elif "keputusan" in lower or "key decisions" in lower:
            if current_sec and buffer:
                sections[current_sec] = "\n".join(buffer).strip()
            current_sec = "decisions"
            buffer = []
        elif "tindakan" in lower or "action items" in lower:
            if current_sec and buffer:
                sections[current_sec] = "\n".join(buffer).strip()
            current_sec = "action_items"
            buffer = []
        else:
            buffer.append(line)

    if current_sec and buffer:
        sections[current_sec] = "\n".join(buffer).strip()

    return sections
