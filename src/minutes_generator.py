"""
STTMeet Minutes Generator
Generates Meeting Minutes based on specialized templates from docs/meeting_minute:
- action_minutes: Objective, Prior Action items review, Agenda & Decisions, Action Item Register.
- discussion_minutes: Call to Order, Discussion Records by Agenda Item, Directives & Next Steps.
- three_column: Item # | Discussion & Deliberation | Action Required & Decision | Responsibility & Deadline table.
- board_governance: Call to Order & Quorum, Approval of Previous Minutes, Matters for Resolution, Reports, Adjournment & Signatures.

Supports Bahasa Melayu and English. A bilingual mode used to exist here but
was removed: interleaved Malay/English output degraded both languages and made
the exported documents read as mixed-language.
"""
from typing import Dict, Any, Callable, Optional, List
from google import genai

from .config import MINUTES_MODEL_NAME, MINUTES_FALLBACK_MODELS
from .gemini_failover import FailoverCall, generate_with_failover
from .logger import get_logger

log = get_logger(__name__)

# Divergence between the generation call sites is deliberate and user-visible,
# so it is spelled out here rather than inherited silently. The Minutes and
# Action items paths happen to agree with Recap today; they are named apart so
# that changing one path's policy cannot silently change another's.
MINUTES_BACKOFF_STEP_SECONDS = 5
MINUTES_TEMPERATURE = 0.2
MINUTES_QUOTA_FAILURE_MESSAGE = (
    "All available Gemini models ({models}) exceeded daily free quotas or failed.\n"
    "Please check your Google AI Studio quota limits or retry tomorrow."
)

ACTION_ITEMS_BACKOFF_STEP_SECONDS = 5
ACTION_ITEMS_TEMPERATURE = 0.2
ACTION_ITEMS_QUOTA_FAILURE_MESSAGE = (
    "All available Gemini models ({models}) exceeded daily free quotas or failed.\n"
    "Please check your Google AI Studio quota limits or retry tomorrow."
)

# Template-based synthesis prompts structured per template and language.
TEMPLATES_PROMPTS = {
    "action_minutes": {
        "Bahasa Melayu": """Anda adalah setiausaha mesyuarat profesional.
Berdasarkan transkrip mesyuarat di bawah, hasilkan Minit Tindakan Mesyuarat (Action Minutes) rasmi dalam Bahasa Melayu mengikut struktur berikut:

# Minit Tindakan Mesyuarat (Action Minutes)

**Tajuk Mesyuarat:** [Nama Projek / Penyelarasan Pasukan]  
**Tarikh & Masa:** [Tarikh, Masa]  
**Tempat / Pautan:** [Bilik Mesyuarat / Pautan Video]  
**Pengerusi:** [Nama Pengerusi]  
**Pencatat Minit:** [Nama Pencatat]  
**Kehadiran:** [Senarai Kehadiran]  
**Tidak Hadir:** [Senarai Tidak Hadir]  

---

## 1. Objektif Mesyuarat
[Ringkasan 1–2 ayat mengenai matlamat utama mesyuarat.]

---

## 2. Semakan Tindakan Terdahulu
* **[Tindakan dari mesyuarat lalu jika ada]:** [Status: Selesai / Dalam Tindakan / Ditangguhkan] — *Nota:* [Konteks ringkas jika ada].

---

## 3. Agenda & Keputusan Yang Dicapai

### Agenda 1: [Tajuk Perbincangan / Topik]
* **Ringkasan Hasil:** [Kenyataan ringkas perkara yang dipersetujui].
* **Keputusan Rasmi:** [Keputusan muktamad tanpa butiran perdebatan berpanjangan].

### Agenda 2: [Tajuk Perbincangan / Topik]
* **Ringkasan Hasil:** [Kenyataan ringkas perkara yang dipersetujui].
* **Keputusan Rasmi:** [Keputusan muktamad].

---

## 4. Daftar Tindakan (Action Item Register)

| Bil | Tindakan / Tugasan | Pegawai Bertanggungjawab (PIC) | Tarikh Akhir | Status |
| :- | :--- | :--- | :--- | :--- |
| 1 | [Penerangan tindakan yang jelas] | [Nama] | [Tarikh] | Terbuka |
(Senaraikan semua tugasan dan komitmen tindakan secara konkrit)

---

## 5. Mesyuarat Seterusnya
* **Tarikh & Masa:** [Tarikh & Masa jika dibincangkan]  
* **Agenda Cadangan:** [Perkara utama untuk sesi akan datang]  

TRANSKRIP MESYUARAT:
{transcript}
""",
        "English": """You are an executive meeting secretary.
Based on the meeting transcript below, generate professional Action Minutes in English adhering strictly to this format:

# Action Minutes of Meeting

**Meeting Title:** [Project Name / Team Operational Sync]  
**Date & Time:** [DD Month YYYY, HH:MM AM/PM]  
**Location / Link:** [Meeting Room / Video Conference Link]  
**Chairperson:** [Name]  
**Minute Taker:** [Name]  
**Attendees:** [List of Attendees]  
**Absentees:** [List of Absentees]  

---

## 1. Meeting Objective
[Brief 1–2 sentence statement of the meeting's primary goal.]

---

## 2. Review of Prior Action Items
* **[Action Item from previous meeting if mentioned]:** [Status: Completed / In Progress / Deferred] — *Notes:* [Brief context].

---

## 3. Agenda Items & Decisions Reached

### Agenda Item 1: [Topic / Milestone Name]
* **Summary of Outcome:** [Concise statement of what was agreed].
* **Formal Decision:** [Final decision reached without unnecessary debate details].

### Agenda Item 2: [Topic / Milestone Name]
* **Summary of Outcome:** [Concise statement of what was agreed].
* **Formal Decision:** [Final decision reached].

---

## 4. Action Item Register

| # | Action Item / Deliverable | Owner | Target Due Date | Status |
| :- | :--- | :--- | :--- | :--- |
| 1 | [Clear, actionable description] | [Name] | [DD/MM/YYYY] | Open |
(Extract all concrete commitments and tasks)

---

## 5. Next Meeting
* **Date & Time:** [DD Month YYYY, HH:MM AM/PM if mentioned]  
* **Tentative Agenda:** [Key items to cover]  

TRANSCRIPT:
{transcript}
""",
    },

    "discussion_minutes": {
        "Bahasa Melayu": """Anda adalah setiausaha mesyuarat profesional.
Berdasarkan transkrip mesyuarat di bawah, hasilkan Minit Perbincangan Topikal (Discussion Minutes) rasmi dalam Bahasa Melayu mengikut struktur berikut:

# Minit Perbincangan Mesyuarat (Discussion Minutes)

**Jawatankuasa / Kumpulan:** [Nama Jawatankuasa / Pasukan Kerja]  
**Tarikh & Masa:** [Tarikh, Masa]  
**Tempat / Platform:** [Bilik Mesyuarat / Pautan Maya]  
**Pengerusi:** [Nama Pengerusi]  
**Pencatat Minit:** [Nama Pencatat]  
**Ahli Hadir:** [Senarai Hadir]  
**Penceramah Jemputan:** [Nama jika ada]  
**Maaf / Tidak Hadir:** [Senarai Maaf Tidak Hadir]  

---

## 1. Pembukaan & Aluan (Call to Order & Welcome)
[Pengerusi memulakan mesyuarat pada jam sekian. Pengesahan agenda mesyuarat.]

---

## 2. Rekod Perbincangan Mengikut Agenda

### Perkara 1: [Topik Perbincangan / Cadangan Strategik]
* **Latar Belakang & Pembentangan:**  
  [Ringkasan isu, fakta, atau cadangan yang dibentangkan].
* **Hujah Utama & Pandangan Dipertimbangkan:**  
  * Pandangan menyokong: [Ringkasan pandangan menyokong].
  * Kebimbangan / Hujah balas: [Risiko, kekangan kos, masa atau isu dibangkitkan].
  * Alternatif dinilai: [Pilihan lain yang dipertimbangkan].
* **Konsensus / Resolusi:**  
  [Ketetapan bersama yang dicapai oleh ahli mesyuarat].

### Perkara 2: [Topik Perbincangan Seterusnya]
* **Latar Belakang & Pembentangan:**  
  [Ringkasan pembentangan].
* **Hujah Utama & Pandangan Dipertimbangkan:**  
  * [Pandangan atau perbincangan utama].
* **Konsensus / Resolusi:**  
  [Kesimpulan atau arahan kepada pasukan kerja].

---

## 3. Arahan & Langkah Seterusnya (Directives & Next Steps)

| Rujukan | Arahan / Tugasan Siasatan | Pegawai / Bahagian Bertanggungjawab | Tarikh Akhir |
| :--- | :--- | :--- | :--- |
| Perkara 1 | [Penyediaan laporan / tindakan susulan] | [Nama / Bahagian] | [Tarikh] |
| Perkara 2 | [Tugasan susulan] | [Nama / Bahagian] | [Tarikh] |

---

## 4. Penangguhan Mesyuarat (Adjournment)
Mesyuarat ditangguhkan pada jam [Masa].  
**Sesi Seterusnya:** [Tarikh & Masa jika ada].

TRANSKRIP MESYUARAT:
{transcript}
""",
        "English": """You are an executive meeting secretary.
Based on the meeting transcript below, generate detailed Discussion (Topical) Minutes in English following this structure:

# Discussion (Topical) Minutes of Meeting

**Committee / Group:** [Strategy Committee / Policy Taskforce / Steering Group]  
**Date & Time:** [DD Month YYYY, HH:MM AM/PM]  
**Location / Platform:** [Room Name / Virtual Platform]  
**Chairperson:** [Name]  
**Minute Taker:** [Name]  
**Members Present:** [List of Members Present]  
**Guest Presenters:** [Guest Presenters if any]  
**Regrets / Apologies:** [List of Apologies]  

---

## 1. Call to Order & Welcome
[Chairperson Name called the meeting to order. Approval of agenda.]

---

## 2. Discussion Records by Agenda Item

### Item 1: [Strategic Proposal / Policy Review Topic]
* **Background & Presentation:**  
  [Presenter Name introduced the proposal regarding summary of facts, data, or proposed change].
* **Key Arguments & Perspectives Considered:**  
  * Point in favor: [Summary of viewpoint supporting the option].
  * Concerns / Counterpoints: [Risks, cost constraints, or timeline concerns raised].
  * Alternatives weighed: [Other options considered and why they were retained or eliminated].
* **Consensus / Resolution:**  
  [The committee reached consensus to proceed with selected approach].

### Item 2: [Operational / Organizational Review Topic]
* **Background & Presentation:**  
  [Summary of issue or report presented].
* **Key Arguments & Perspectives Considered:**  
  * [Key discussion theme 1].
  * [Key discussion theme 2].
* **Consensus / Resolution:**  
  [Conclusion or instruction given to the working team].

---

## 3. Directives & Next Steps

| Reference | Directive / Assigned Investigation | Lead Individual / Department | Deadline |
| :--- | :--- | :--- | :--- |
| Item 1 | [Prepare revised plan/projections] | [Name / Department] | [DD/MM/YYYY] |
| Item 2 | [Draft updated guidelines] | [Name / Department] | [DD/MM/YYYY] |

---

## 4. Adjournment
The meeting adjourned at [HH:MM AM/PM].  
**Next Session:** [DD Month YYYY, HH:MM AM/PM at Location if mentioned].  

TRANSCRIPT:
{transcript}
""",
    },

    "three_column": {
        "Bahasa Melayu": """Anda adalah setiausaha mesyuarat profesional.
Berdasarkan transkrip mesyuarat di bawah, hasilkan Minit Tiga Lajur (Three-Column Minutes) dalam Bahasa Melayu standard mengikut format jadual matriks berikut:

# Minit Mesyuarat Tiga Lajur (Three-Column Minutes)

**Projek / Penyelarasan:** [Nama Projek / Penyelarasan Tapak / Semakan Pembekal]  
**Tarikh Mesyuarat:** [Tarikh] | **Masa:** [Masa Mula - Masa Tamat]  
**Tempat:** [Bilik Mesyuarat / Pejabat Tapak / Pautan Video]  
**Fasilitator / Pengerusi:** [Nama] | **Pencatat Nota:** [Nama]  
**Kehadiran:** [Senarai Kehadiran bersama Bahagian / Organisasi]  

---

| Perkara | Perbincangan & Pertimbangan | Tindakan Diperlukan & Keputusan | Tanggungjawab & Tarikh Akhir |
| :---: | :--- | :--- | :---: |
| **1.0** | **[Tajuk Agenda 1]**<br>[Ringkasan terperinci perbincangan, maklum balas dan pertimbangan utama]. | [Tindakan konkrit yang perlu diambil dan keputusan rasmi]. | **[Nama Pegawai / PIC]**<br>*Tarikh: DD/MM/YYYY* |
| **2.0** | **[Tajuk Agenda 2]**<br>[Perbincangan mengenai cabaran, cadangan atau kemajuan]. | [Ketetapan tindakan dan arahan susulan]. | **[Nama Pegawai / PIC]**<br>*Tarikh: DD/MM/YYYY* |
| **3.0** | **[Tajuk Agenda 3]**<br>[Isu teknikal/operasi/kewangan yang dibincangkan]. | [Kelulusan atau langkah pemulihan]. | **[Nama Pegawai / PIC]**<br>*Tarikh: DD/MM/YYYY* |
| **4.0** | **Hal-Hal Lain (AOB)**<br>[Perkara berbangkit lain atau pengumuman jika ada]. | [Tindakan susulan]. | **[Nama Pegawai / PIC]**<br>*Tarikh: DD/MM/YYYY* |

---

**Butiran Mesyuarat Seterusnya:** [Tarikh dan Masa jika dibincangkan]

TRANSKRIP MESYUARAT:
{transcript}
""",
        "English": """You are an executive meeting secretary.
Based on the meeting transcript below, generate structured Three-Column Meeting Minutes in English following this exact layout:

# Three-Column Meeting Minutes

**Project / Coordination:** [Project Name / Site Coordination / Vendor Review]  
**Meeting Date:** [DD Month YYYY] | **Time:** [HH:MM AM/PM - HH:MM AM/PM]  
**Location:** [Meeting Room / Site Office / Video Link]  
**Facilitator:** [Name] | **Notes Prepared By:** [Name]  
**Attendees:** [List of Attendees with Company / Dept Affiliation]  

---

| Item # | Discussion & Deliberation | Action Required & Decision | Responsibility & Deadline |
| :---: | :--- | :--- | :---: |
| **1.0** | **[Agenda Topic 1]**<br>[Detailed summary of background, arguments, and considerations]. | [Clear statement of required action and official decision]. | **[Lead Name / PIC]**<br>*Due: DD/MM/YYYY* |
| **2.0** | **[Agenda Topic 2]**<br>[Discussion of challenges, proposals, or project status]. | [Action directive and decision]. | **[Lead Name / PIC]**<br>*Due: DD/MM/YYYY* |
| **3.0** | **[Agenda Topic 3]**<br>[Deliberation on technical, commercial, or operational items]. | [Resolution or action plan]. | **[Lead Name / PIC]**<br>*Due: DD/MM/YYYY* |
| **4.0** | **Any Other Business (AOB)**<br>[Secondary matters or schedule announcements]. | [Action item]. | **[Lead Name / PIC]**<br>*Due: DD/MM/YYYY* |

---

**Next Meeting Details:** [DD Month YYYY at HH:MM AM/PM if mentioned]

TRANSCRIPT:
{transcript}
""",
    },

    "board_governance": {
        "Bahasa Melayu": """Anda adalah setiausaha syarikat dan mesyuarat korporat yang profesional.
Berdasarkan transkrip mesyuarat di bawah, hasilkan Minit Rasmi Lembaga Pengarah / Tadbir Urus (Formal Board of Directors Meeting Minutes) dalam Bahasa Melayu standard mengikut format tadbir urus korporat berikut:

# Minit Rasmi Mesyuarat Lembaga Pengarah

**Nama Organisasi:** [Nama Syarikat / Organisasi]  
**Jenis Mesyuarat:** Mesyuarat [Biasa / Khas / Tahunan] Lembaga Pengarah  
**Tarikh & Masa:** [Tarikh, Masa]  
**Tempat:** [Alamat Pejabat Berdaftar / Bilik Mesyuarat Maya Selamat]  

---

## 1. Pembukaan & Kehadiran
* **Panggilan Mesyuarat:** Mesyuarat dimulakan pada jam [Masa] oleh [Nama Pengerusi], Pengerusi Lembaga Pengarah.
* **Pegawai Mesyuarat:** [Nama Pengerusi] mempengerusikan mesyuarat; [Nama Setiausaha] mencatat minit mesyuarat.
* **Pengarah Hadir:** [Senarai Pengarah yang Hadir]  
* **Pengarah Tidak Hadir (Dengan Maaf):** [Senarai Pengarah Tidak Hadir]  
* **Turut Hadir / Atas Jemputan:** [Penasihat Undang-Undang, CFO, Juruaudit, dll.]  
* **Korum Mesyuarat:** Setiausaha mengesahkan bahawa korum mesyuarat mencukupi selaras dengan Perlembagaan Syarikat.

---

## 2. Pengesahan Minit Mesyuarat Yang Lalu
Minit mesyuarat Lembaga Pengarah yang diadakan pada [Tarikh Mesyuarat Lalu] telah diteliti.  
* **Ketetapan:** Atas usul oleh [Nama Pengarah] dan disokong oleh [Nama Pengarah], dipersetujui sebulat suara bahawa minit mesyuarat lalu disahkan dan diterima tanpa pindaan.

---

## 3. Perkara Untuk Ketetapan & Usul Rasmi

### Resolusi 1: [Tajuk Usul, contohnya: Kelulusan Belanjawan Tahunan]
* **Pembentangan:** [Nama Eksekutif / Pengarah] membentangkan [laporan/usul berkaitan].
* **Usul:** Dicadangkan oleh [Nama Pengarah] dan disokong oleh [Nama Pengarah] bahawa:
  > *"DIPERSETUJUI, bahawa Lembaga Pengarah dengan ini meluluskan [teks penuh resolusi rasmi]."*
* **Undian:**  
  * Menyokong: [Kiraan undi atau "Sebulat Suara"]  
  * Menentang: [Kiraan undi atau "Tiada"]  
  * Berkecuali: [Nama jika ada pengisytiharan percanggahan kepentingan]  
  * **Keputusan:** Usul diluluskan sebulat suara.

### Resolusi 2: [Tajuk Usul Seterusnya]
* **Pembentangan:** [Penerangan ringkas mengenai keperluan].
* **Usul:** Dicadangkan oleh [Nama Pengarah] dan disokong oleh [Nama Pengarah] bahawa:
  > *"DIPERSETUJUI, bahawa [Nama / Jawatan] diberi kuasa untuk melaksanakan [kontrak/dokumen] bagi pihak Syarikat."*
* **Undian:**  
  * Menyokong: [Kiraan] | Menentang: [Kiraan] | Berkecuali: [Kiraan]  
  * **Keputusan:** Usul diluluskan.

---

## 4. Laporan Yang Diterima
* **Laporan Kewangan:** [Nama CFO] membentangkan penyata kewangan suku tahun. Laporan diterima sebulat suara seperti dibentangkan.
* **Laporan Ketua Pegawai Eksekutif:** [Nama CEO] melaporkan prestasi perniagaan dan inisiatif utama syarikat.

---

## 5. Penangguhan & Tandatangan
Mesyuarat ditangguhkan pada jam [Masa].  

**Minit Disediakan Oleh:**  

____________________________________  
[Nama Setiausaha], Setiausaha Syarikat  
Tarikh: [Tarikh]  

**Minit Disahkan Oleh:**  

____________________________________  
[Nama Pengerusi], Pengerusi Lembaga Pengarah  
Tarikh: [Tarikh]  

TRANSKRIP MESYUARAT:
{transcript}
""",
        "English": """You are a corporate board secretary.
Based on the meeting transcript below, generate Formal Board of Directors Meeting Minutes in English following standard governance structure:

# Formal Board of Directors Meeting Minutes

**Organization Name:** [Company / Organization Name]  
**Meeting Type:** [Regular / Special / Annual] Meeting of the Board of Directors  
**Date & Time:** [DD Month YYYY, HH:MM AM/PM]  
**Location:** [Registered Office Address / Secure Virtual Meeting Room]  

---

## 1. Opening & Attendance
* **Call to Order:** The meeting was called to order at [HH:MM AM/PM] by [Name], Chairperson.
* **Presiding Officers:** [Chairperson Name] presided; [Secretary Name] recorded the minutes.
* **Directors Present:** [List of Directors Present]  
* **Directors Absent:** [List of Absent Directors]  
* **In Attendance / By Invitation:** [Legal Counsel, CFO, Auditor, etc.]  
* **Quorum:** The Secretary confirmed that a quorum was present pursuant to the Company's Bylaws / Articles of Association.

---

## 2. Approval of Previous Minutes
The minutes of the previous Board meeting held on [Date of Last Meeting] were reviewed.  
* **Resolution:** Upon motion duly made by [Director Name] and seconded by [Director Name], it was unanimously resolved that the minutes of the meeting held on [Date of Last Meeting] be approved as circulated.

---

## 3. Matters for Resolution & Formal Motions

### Resolution 1: [Subject of Motion, e.g., Approval of Annual Budget]
* **Presentation:** [Executive / Director Name] presented the proposed report/item.
* **Motion:** It was moved by [Director Name] and seconded by [Director Name] that:
  > *"RESOLVED, that the Board of Directors hereby approves [exact text of formal resolution]."*
* **Vote:**  
  * In Favor: [Count or "Unanimous"]  
  * Opposed: [Count or "None"]  
  * Abstentions: [Names, if any, with conflict of interest disclosures]  
  * **Disposition:** Motion carried.

### Resolution 2: [Subject of Motion, e.g., Authorization of Contract / Signatory]
* **Presentation:** [Brief explanation of the requirement].
* **Motion:** It was moved by [Director Name] and seconded by [Director Name] that:
  > *"RESOLVED, that [Officer Name/Title] is authorized to execute [contract/document] on behalf of the Company."*
* **Vote:**  
  * In Favor: [Count] | Opposed: [Count] | Abstentions: [Count]  
  * **Disposition:** Motion carried.

---

## 4. Reports Received
* **Financial Report:** [CFO Name] delivered the quarterly financial statement. The report was accepted as presented.
* **Chief Executive Report:** [CEO Name] reported on company performance and key initiatives.

---

## 5. Adjournment & Signatures
There being no further business, the meeting was adjourned at [HH:MM AM/PM].  

**Minutes Submitted By:**  

____________________________________  
[Secretary Name], Corporate Secretary  
Date: [DD/MM/YYYY]  

**Minutes Approved By:**  

____________________________________  
[Chairperson Name], Chairperson of the Board  
Date: [DD/MM/YYYY]  

TRANSCRIPT:
{transcript}
""",
    }
}

# Backward compatibility alias
MINUTES_SYNTHESIS_PROMPTS = TEMPLATES_PROMPTS["action_minutes"]


def get_synthesis_prompt(template: str = "action_minutes", language: str = "Bahasa Melayu") -> str:
    """Retrieve the prompt template for a specific template key and language."""
    tmpl_group = TEMPLATES_PROMPTS.get(template) or TEMPLATES_PROMPTS["action_minutes"]
    return tmpl_group.get(language) or tmpl_group.get("Bahasa Melayu") or TEMPLATES_PROMPTS["action_minutes"]["Bahasa Melayu"]


def generate_meeting_minutes(
    client: genai.Client,
    full_transcript: str,
    language: str = "Bahasa Melayu",
    template: str = "action_minutes",
    progress_callback: Optional[Callable[[str], None]] = None,
    max_retries: int = 3,
    model_override: Optional[str] = None,
    cancel_event=None
) -> str:
    """
    Synthesize meeting transcript into structured meeting minutes using the specified template.

    Retry, backoff, Quota failure detection and failover are owned by the shared
    policy in gemini_failover; this module keeps the Minutes prompt table and
    describes what makes a Minutes call different.

    Pass a threading.Event as cancel_event to abandon the run; raises CancelledError.
    """
    log.info(
        "Generating meeting minutes in language '%s', template '%s' (transcript length: %d chars)",
        language, template, len(full_transcript)
    )
    if progress_callback:
        progress_callback(f"Generating minutes ({template}) in {language}...")

    prompt_template = get_synthesis_prompt(template=template, language=language)
    full_prompt = prompt_template.format(transcript=full_transcript)

    preferred = model_override or MINUTES_MODEL_NAME
    models_to_try = [preferred] + [m for m in MINUTES_FALLBACK_MODELS if m != preferred]

    return generate_with_failover(client, FailoverCall(
        description="minutes synthesis",
        label="minutes",
        contents=[full_prompt],
        models=models_to_try,
        max_retries=max_retries,
        backoff_step=MINUTES_BACKOFF_STEP_SECONDS,
        temperature=MINUTES_TEMPERATURE,
        final_error=MINUTES_QUOTA_FAILURE_MESSAGE.format(models=", ".join(models_to_try)),
        progress_callback=progress_callback,
        cancel_event=cancel_event,
    ))


ACTION_ITEMS_PROMPTS = {
    "English": """You are an executive project manager and meeting secretary.
Based on the meeting transcript below, identify and compile all actionable tasks, commitments, decisions requiring execution, and deliverables into an Action Item Register adhering strictly to this structure:

# Action Items & Deliverables

## Action Item Register

| # | Task / Deliverable | Owner / PIC | Target Due Date | Status |
| :- | :--- | :--- | :--- | :--- |
| 1 | [Clear, specific, actionable description] | [Name] | [DD/MM/YYYY or TBD] | Not Started / Open |

## Critical Dependencies & Blockers
* **[Item 1]:** [Details of dependency or required milestone before next step].

## Follow-up Requirements
* **[Follow-up 1]:** [Review schedule, check-in date, or communication channel].

TRANSCRIPT:
{transcript}
""",
    "Bahasa Melayu": """Anda adalah pengurus projek dan setiausaha mesyuarat profesional.
Berdasarkan transkrip mesyuarat di bawah, kenal pasti dan susun semua tindakan, komitmen, keputusan yang memerlukan pelaksanaan, dan penyerahan tugas ke dalam Daftar Tindakan rasmi mengikut struktur berikut:

# Senarai Tindakan Mesyuarat (Action Items)

## Daftar Tindakan (Action Item Register)

| Bil | Tindakan / Tugasan | Pegawai Bertanggungjawab (PIC) | Tarikh Akhir | Status |
| :- | :--- | :--- | :--- | :--- |
| 1 | [Penerangan tindakan yang jelas, tepat, dan boleh dilaksanakan] | [Nama] | [Tarikh atau Belum Ditetapkan] | Belum Mula / Terbuka |

## Kebergantungan Kritikal & Kekangan
* **[Perkara 1]:** [Butiran kebergantungan atau kelulusan yang diperlukan sebelum langkah seterusnya].

## Keperluan Susulan
* **[Susulan 1]:** [Jadual semakan semula atau saluran komunikasi yang dipersetujui].

TRANSKRIP MESYUARAT:
{transcript}
""",
}


def get_action_items_prompt(language: str = "Bahasa Melayu") -> str:
    """Retrieve prompt for generating action items."""
    return ACTION_ITEMS_PROMPTS.get(language) or ACTION_ITEMS_PROMPTS.get("English") or ACTION_ITEMS_PROMPTS["Bahasa Melayu"]


def generate_action_items(
    client: genai.Client,
    full_transcript: str,
    language: str = "Bahasa Melayu",
    progress_callback: Optional[Callable[[str], None]] = None,
    max_retries: int = 3,
    model_override: Optional[str] = None,
    cancel_event=None
) -> str:
    """
    Synthesize meeting transcript into a standalone Action Item Register.

    Retry, backoff, Quota failure detection and failover are owned by the shared
    policy in gemini_failover; this module keeps the Action items prompt table
    and describes what makes an Action items call different.
    """
    log.info(
        "Generating action items in language '%s' (transcript length: %d chars)",
        language, len(full_transcript)
    )
    if progress_callback:
        progress_callback(f"Generating action items in {language}...")

    prompt_template = get_action_items_prompt(language=language)
    full_prompt = prompt_template.format(transcript=full_transcript)

    preferred = model_override or MINUTES_MODEL_NAME
    models_to_try = [preferred] + [m for m in MINUTES_FALLBACK_MODELS if m != preferred]

    return generate_with_failover(client, FailoverCall(
        description="action items synthesis",
        label="action items",
        contents=[full_prompt],
        models=models_to_try,
        max_retries=max_retries,
        backoff_step=ACTION_ITEMS_BACKOFF_STEP_SECONDS,
        temperature=ACTION_ITEMS_TEMPERATURE,
        final_error=ACTION_ITEMS_QUOTA_FAILURE_MESSAGE.format(models=", ".join(models_to_try)),
        progress_callback=progress_callback,
        cancel_event=cancel_event,
    ))


def parse_minutes_sections(minutes_text: str) -> Dict[str, str]:
    """
    Extract individual sections (Summary/Discussion, Decisions/Resolutions, Action Items/Directives)
    from generated minutes markdown adaptively across different templates.
    """
    sections = {
        "summary": "",
        "highlights": "",
        "decisions": "",
        "action_items": "",
        "full_text": minutes_text
    }

    if not minutes_text.strip():
        return sections

    lines = minutes_text.splitlines()
    summary_parts = []
    actions_parts = []
    decisions_parts = []
    highlights_parts = []

    # Section-based classification
    current_bucket = None

    for line in lines:
        lower = line.lower()

        # Heading detection
        if line.strip().startswith("#"):
            if any(k in lower for k in [
                "objektif", "objective", "ringkasan", "summary",
                "call to order", "pembukaan", "opening & attendance"
            ]):
                current_bucket = "summary"
                summary_parts.append(line)
                continue
            elif any(k in lower for k in [
                "agenda & keputusan", "agenda items & decisions", "rekod perbincangan",
                "discussion records", "discussion highlights", "perkara", "item "
            ]):
                current_bucket = "highlights"
                highlights_parts.append(line)
                continue
            elif any(k in lower for k in [
                "resolusi", "resolution", "matters for resolution", "keputusan", "key decisions"
            ]):
                current_bucket = "decisions"
                decisions_parts.append(line)
                continue
            elif any(k in lower for k in [
                "daftar tindakan", "action item register", "arahan & langkah",
                "directives & next steps", "tindakan", "action items matrix"
            ]):
                current_bucket = "action_items"
                actions_parts.append(line)
                continue
            elif any(k in lower for k in [
                "adjournment", "penangguhan", "mesyuarat seterusnya", "next meeting", "laporan yang diterima", "reports received"
            ]):
                current_bucket = "other"
                continue

        # Add line to current bucket
        if current_bucket == "summary":
            summary_parts.append(line)
        elif current_bucket == "highlights":
            highlights_parts.append(line)
            if "keputusan" in lower or "decision" in lower or "resolusi" in lower:
                decisions_parts.append(line)
        elif current_bucket == "decisions":
            decisions_parts.append(line)
        elif current_bucket == "action_items":
            actions_parts.append(line)

    # For Three-Column template or general tables, extract table if action_items was empty
    if not "".join(actions_parts).strip():
        table_lines = [l for l in lines if l.strip().startswith("|")]
        if len(table_lines) >= 3:
            actions_parts = table_lines

    # If summary is empty, gather introductory bullet points or first few paragraphs
    if not "".join(summary_parts).strip():
        intro = []
        for l in lines[:30]:
            if l.strip().startswith("#"):
                continue
            if l.strip().startswith("|"):
                break
            intro.append(l)
        summary_parts = intro

    sections["summary"] = "\n".join(summary_parts).strip()
    sections["highlights"] = "\n".join(highlights_parts).strip()
    sections["decisions"] = "\n".join(decisions_parts).strip()
    sections["action_items"] = "\n".join(actions_parts).strip()

    return sections
