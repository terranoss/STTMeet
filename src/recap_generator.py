"""
STTMeet Meeting Recap Generator
Generates Executive Meeting Recaps based on docs/executive_meeting_recap_template.md:
- Executive Summary (TL;DR)
- Key Decisions Made
- Action Items & Deliverables Matrix
- Strategic Discussion & Topic Highlights
- Risks, Dependencies & Blockers
- Open Items & Parking Lot
- Next Scheduled Meeting

Supports English and Bahasa Melayu. A bilingual mode used to exist here but
was removed: interleaved Malay/English output degraded both languages and made
the exported documents read as mixed-language.
"""
from typing import Dict, Any, Callable, Optional, List
from google import genai
from google.genai import types

from .cancellation import CancelledError, cancellable_sleep, raise_if_cancelled
from .config import MINUTES_MODEL_NAME, MINUTES_FALLBACK_MODELS, MAX_OUTPUT_TOKENS
from .logger import get_logger

log = get_logger(__name__)

RECAP_PROMPTS = {
    "English": """You are an executive-level executive assistant and project management professional.
Based on the meeting transcript below, produce an Executive Meeting Recap strictly following this format and structure:

# Executive Meeting Recap

**Meeting Title:** [Project Name / Steering Committee / Strategic Sync]  
**Date & Time:** [DD Month YYYY, HH:MM AM/PM]  
**Duration:** [e.g., 45 mins]  
**Facilitator:** [Name]  
**Attendees:** [Name 1, Name 2, Name 3]  
**Absent / Apologies:** [Name]  

---

## 1. Executive Summary (TL;DR)
> A concise 2–3 sentence overview of the meeting's primary objective, core alignment reached, and overall direction.

* [Sentence 1: Purpose of meeting and key updates reviewed]
* [Sentence 2: Major consensus or pivot agreed upon]
* [Sentence 3: Immediate priority for the upcoming cycle]

---

## 2. Key Decisions Made
*High-impact decisions finalized during this session to eliminate ambiguity.*

* **Decision 1:** [Clear statement of decision] — *Rationale:* [Brief 1-sentence reason or trade-off accepted].
* **Decision 2:** [Clear statement of decision] — *Rationale:* [Brief 1-sentence reason].
* **Decision 3:** [Clear statement of decision] — *Rationale:* [Brief 1-sentence reason].

---

## 3. Action Items & Deliverables

| Task / Deliverable | Owner | Target Due Date | Status |
| :--- | :--- | :--- | :--- |
| [Specific, actionable task description] | [Name] | [DD/MM/YYYY] | Not Started |
| [Specific, actionable task description] | [Name] | [DD/MM/YYYY] | In Progress |
| [Specific, actionable task description] | [Name] | [DD/MM/YYYY] | Blocked |

---

## 4. Strategic Discussion & Topic Highlights

### Topic A: [Key Agenda Theme / Strategic Pillar]
* **Context & Findings:** [Summary of presented data or market/internal context].
* **Key Perspectives:** [Notable feedback, support, or objections raised by attendees].
* **Outcome:** [Conclusion reached or next step on this topic].

### Topic B: [Budget, Timeline, or Resource Allocation]
* **Context & Findings:** [Financial, timeline, or resource implications discussed].
* **Key Perspectives:** [Points of caution or consensus].
* **Outcome:** [Agreed budget limits or schedule adjustments].

---

## 5. Risks, Dependencies & Blockers
* **[Risk/Blocker 1]:** [Description of threat to timeline, scope, or budget] — *Mitigation/Assigned to:* [Owner].
* **[Dependency 2]:** [External approval or upstream deliverable needed before proceeding].

---

## 6. Open Items & Parking Lot
*Topics tabled for future sessions or requiring asynchronous discovery.*

* **Item 1:** [Topic deferred due to lack of data or out of scope].
* **Item 2:** [Follow-up item to be handled via email/Slack].

---

**Next Scheduled Meeting:** [Date, Time, or "Asynchronous follow-up on DD/MM/YYYY"]

TRANSCRIPT:
{transcript}
""",
    "Bahasa Melayu": """Anda adalah pembantu eksekutif dan pengurus projek profesional.
Berdasarkan transkrip mesyuarat di bawah, hasilkan Rekap Mesyuarat Eksekutif (Executive Meeting Recap) rasmi dalam Bahasa Melayu mengikut struktur berikut:

# Rekap Mesyuarat Eksekutif (Executive Meeting Recap)

**Tajuk Mesyuarat:** [Nama Projek / Jawatankuasa Pemandu / Penyelarasan Strategik]  
**Tarikh & Masa:** [Tarikh, Masa]  
**Tempoh:** [cth., 45 minit]  
**Fasilitator / Pengerusi:** [Nama]  
**Kehadiran:** [Nama 1, Nama 2, Nama 3]  
**Tidak Hadir / Maaf:** [Nama]  

---

## 1. Ringkasan Eksekutif (TL;DR)
> Gambaran ringkas 2–3 ayat mengenai objektif utama mesyuarat, persetujuan bersama yang dicapai, dan hala tuju keseluruhan.

* [Ayat 1: Tujuan mesyuarat dan kemas kini utama yang disemak]
* [Ayat 2: Konsensus atau peralihan utama yang dipersetujui]
* [Ayat 3: Keutamaan serta-merta untuk kitaran akan datang]

---

## 2. Keputusan Utama Yang Dicapai
*Keputusan berimpak tinggi yang dimuktamadkan semasa sesi ini untuk mengelakkan sebarang kekaburan.*

* **Keputusan 1:** [Kenyataan jelas mengenai keputusan] — *Rasional:* [Sebab ringkas 1 ayat atau kompromi yang dipersetujui].
* **Keputusan 2:** [Kenyataan jelas mengenai keputusan] — *Rasional:* [Sebab ringkas 1 ayat].
* **Keputusan 3:** [Kenyataan jelas mengenai keputusan] — *Rasional:* [Sebab ringkas 1 ayat].

---

## 3. Tindakan & Penyerahan (Action Items & Deliverables)

| Tugasan / Penyerahan | Pegawai Bertanggungjawab (PIC) | Tarikh Sasaran | Status |
| :--- | :--- | :--- | :--- |
| [Penerangan tugasan yang spesifik dan boleh diambil tindakan] | [Nama] | [HH/BB/TTTT] | Belum Mula |
| [Penerangan tugasan yang spesifik dan boleh diambil tindakan] | [Nama] | [HH/BB/TTTT] | Dalam Tindakan |
| [Penerangan tugasan yang spesifik dan boleh diambil tindakan] | [Nama] | [HH/BB/TTTT] | Terhalang |

---

## 4. Perbincangan Strategik & Sorotan Topik

### Topik A: [Tema Agenda Utama / Tunjang Strategik]
* **Konteks & Dapatan:** [Ringkasan data yang dibentangkan atau konteks pasaran/dalaman].
* **Pandangan Utama:** [Maklum balas penting, sokongan, atau bantahan yang dibangkitkan oleh peserta].
* **Hasil:** [Kesimpulan yang dicapai atau langkah seterusnya untuk topik ini].

### Topik B: [Bajet, Garis Masa, atau Peruntukan Sumber]
* **Konteks & Dapatan:** [Implikasi kewangan, garis masa, atau sumber yang dibincangkan].
* **Pandangan Utama:** [Perkara yang memerlukan perhatian atau konsensus].
* **Hasil:** [Had belanjawan yang dipersetujui atau pelarasan jadual].

---

## 5. Risiko, Kebergantungan & Kekangan
* **[Risiko/Kekangan 1]:** [Penerangan ancaman terhadap garis masa, skop, atau belanjawan] — *Mitigasi/Ditugaskan kepada:* [Nama PIC].
* **[Kebergantungan 2]:** [Kelulusan pihak luar atau penyerahan awal yang diperlukan sebelum meneruskan tindakan].

---

## 6. Perkara Tertangguh & Parking Lot
*Topik yang ditangguhkan untuk sesi akan datang atau memerlukan maklumat lanjut secara tidak segerak.*

* **Perkara 1:** [Topik ditangguhkan kerana kekurangan data atau di luar skop].
* **Perkara 2:** [Perkara susulan untuk diselesaikan melalui e-mel/Slack].

---

**Mesyuarat Seterusnya Yang Dijadualkan:** [Tarikh, Masa, atau "Tindakan susulan secara tidak segerak pada HH/BB/TTTT"]

TRANSKRIP MESYUARAT:
{transcript}
""",
}


def get_recap_prompt(language: str = "Bahasa Melayu") -> str:
    """Retrieve prompt for the given language."""
    return RECAP_PROMPTS.get(language) or RECAP_PROMPTS.get("English") or RECAP_PROMPTS["Bahasa Melayu"]


def generate_meeting_recap(
    client: genai.Client,
    full_transcript: str,
    language: str = "Bahasa Melayu",
    progress_callback: Optional[Callable[[str], None]] = None,
    max_retries: int = 3,
    model_override: Optional[str] = None,
    cancel_event: Optional[Any] = None
) -> str:
    """
    Synthesize meeting transcript into an Executive Meeting Recap.
    Includes automatic retry with exponential backoff and failover across candidate models.
    """
    log.info(
        "Generating executive meeting recap in language '%s' (transcript length: %d chars)",
        language, len(full_transcript)
    )
    if progress_callback:
        progress_callback(f"Generating meeting recap in {language}...")

    prompt_template = get_recap_prompt(language=language)
    full_prompt = prompt_template.format(transcript=full_transcript)

    preferred = model_override or MINUTES_MODEL_NAME
    models_to_try = [preferred] + [m for m in MINUTES_FALLBACK_MODELS if m != preferred]

    for model_candidate in models_to_try:
        raise_if_cancelled(cancel_event)
        log.info("Attempting recap generation with model: %s", model_candidate)

        for attempt in range(1, max_retries + 1):
            try:
                raise_if_cancelled(cancel_event)
                log.info("Calling Gemini model '%s' for recap synthesis (Attempt %d/%d)...", model_candidate, attempt, max_retries)
                if progress_callback:
                    progress_callback(f"Generating recap with {model_candidate} (Attempt {attempt}/{max_retries})...")

                response = client.models.generate_content(
                    model=model_candidate,
                    contents=[full_prompt],
                    config=types.GenerateContentConfig(
                        max_output_tokens=MAX_OUTPUT_TOKENS,
                        temperature=0.2
                    )
                )
                raise_if_cancelled(cancel_event)
                result = response.text or ""
                log.info("Executive meeting recap generated successfully with '%s' (%d chars).", model_candidate, len(result))
                return result

            except CancelledError:
                raise

            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota exceeded" in err_str.lower():
                    log.warning(
                        "Quota exhausted for model '%s' during recap synthesis. Auto-switching candidate.",
                        model_candidate
                    )
                    if progress_callback:
                        progress_callback(f"Quota reached for {model_candidate}. Auto-switching model...")
                    break

                if attempt < max_retries:
                    wait_sec = attempt * 5
                    if progress_callback:
                        progress_callback(f"Server busy. Retrying in {wait_sec}s (Attempt {attempt + 1}/{max_retries})...")
                    if not cancellable_sleep(cancel_event, wait_sec):
                        raise CancelledError("Retry backoff cancelled by user.")
                else:
                    log.error("All %d recap synthesis attempts failed for '%s': %s", max_retries, model_candidate, err_str[:80])
                    break

    raise RuntimeError(
        f"All available Gemini models ({', '.join(models_to_try)}) exceeded daily free quotas or failed.\n"
        "Please check your Google AI Studio quota limits or retry tomorrow."
    )
