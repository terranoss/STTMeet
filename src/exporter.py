"""
STTMeet Document Exporter
Exports meeting minutes, action items, and transcripts into:
- Microsoft Word (.docx) with formatted headings and styled Action Item tables
- GitHub Flavored Markdown (.md)
- Plain Text (.txt)

Every caller-facing label is localized through i18n.translate(). The document
labels used to be hardcoded bilingual ("Tarikh / Date") regardless of the
interface language, which made exports read as mixed-language.
"""
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from . import config
from .i18n import localize_date, translate

try:
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False


class DocxUnavailableError(RuntimeError):
    """python-docx is not installed, so .docx export cannot proceed."""

    def __init__(self, locale: Optional[str] = None):
        super().__init__(translate("export.docx_missing", locale))
        self.message = translate("export.docx_missing", locale)


def _t(key: str, locale: Optional[str] = None, **fmt: Any) -> str:
    return translate(key, locale, **fmt)


_INLINE_TOKEN_RE = re.compile(
    r'(\*\*.+?\*\*|__.+?__|(?<!\*)\*(?!\*).+?(?<!\*)\*(?!\*)|(?<!_)_(?!_).+?(?<!_)_(?!_)|`[^`]+`)',
    re.DOTALL,
)
_LINK_RE = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\([^)]+\)')


def strip_inline_markdown(text: str) -> str:
    """Remove inline Markdown markers, keeping only the readable text.

    Handles bold (**text**), italic (*text* / _text_), inline code, links
    (label kept, URL dropped), and images (removed entirely).
    """
    if not text:
        return text

    prev = None
    while prev != text:
        prev = text
        text = _IMAGE_RE.sub(r'\1', text)
        text = _LINK_RE.sub(r'\1', text)

    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'__(.+?)__', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'~~(.+?)~~', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\*(?!\s)(.+?)(?<!\s)\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'(?<![A-Za-z0-9_])_(?!\s)(.+?)(?<!\s)_(?![A-Za-z0-9_])', r'\1', text)
    text = re.sub(r'(?<!\w)~{1,2}([^~]+)~{1,2}(?!\w)', r'\1', text)
    return text


def add_markdown_runs(paragraph: Any, text: str, size: Optional[float] = None,
                      bold: Optional[bool] = None, italic: Optional[bool] = None):
    """Add `text` to a docx paragraph, translating inline Markdown into runs.

    **bold** becomes bold Word text, *italic* becomes italic Word text, and
    every other marker is stripped, so no Markdown syntax survives in the
    exported document. `bold`/`italic` of None leave the paragraph style's
    own formatting untouched (used for heading styles).
    """
    if text is None:
        return

    pos = 0
    for match in _INLINE_TOKEN_RE.finditer(text):
        if match.start() > pos:
            _append_run(paragraph, text[pos:match.start()], size, bold, italic)

        token = match.group(0)
        if token.startswith("**") or token.startswith("__"):
            _append_run(paragraph, token[2:-2], size, True,
                        True if italic else None)
        elif token.startswith("`"):
            _append_run(paragraph, token[1:-1], size, bold, italic)
        else:
            _append_run(paragraph, token[1:-1], size, bold, True)
        pos = match.end()

    if pos < len(text):
        _append_run(paragraph, text[pos:], size, bold, italic)


def _append_run(paragraph: Any, text: str, size: Optional[float],
                bold: Optional[bool], italic: Optional[bool]) -> None:
    text = strip_inline_markdown(text)
    if not text:
        return
    run = paragraph.add_run(text)
    if size is not None:
        run.font.size = size
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic


def set_cell_background(cell, hex_color: str):
    """Set background fill color for a table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)

def export_to_docx(
    file_path: str,
    title: str,
    minutes_text: str,
    raw_transcript: Optional[str] = None,
    meeting_meta: Optional[Dict[str, str]] = None,
    locale: Optional[str] = None
) -> str:
    """
    Generate an executive-level Word document (.docx).
    """
    if not DOCX_AVAILABLE:
        raise DocxUnavailableError(locale)

    doc = Document()

    # Document Title
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_before = Pt(0)
    title_p.paragraph_format.space_after = Pt(12)
    add_markdown_runs(title_p, title, Pt(22))
    for run in title_p.runs:
        run.font.size = Pt(22)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0x1A, 0x36, 0x5D) # Navy Blue

    # Metadata Table (Date, Time, Venue, Generated By)
    table = doc.add_table(rows=2, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True

    date_str = localize_date(datetime.now(), locale)
    meta = meeting_meta or {}

    r0c0, r0c1 = table.rows[0].cells
    r1c0, r1c1 = table.rows[1].cells

    r0c0.text = (
        f"{_t('export.meta_date', locale)}: "
        f"{meta.get('date', date_str)}"
    )
    r0c1.text = (
        f"{_t('export.meta_venue', locale)}: "
        f"{meta.get('venue', _t('export.venue_default', locale))}"
    )
    r1c0.text = (
        f"{_t('export.meta_chair', locale)}: "
        f"{meta.get('chair', _t('export.chair_unknown', locale))}"
    )
    r1c1.text = (
        f"{_t('export.meta_generated_by', locale)}: "
        f"STTMeet AI ({config.MODEL_NAME})"
    )

    for row in table.rows:
        for cell in row.cells:
            set_cell_background(cell, "F0F4F8")
            for p in cell.paragraphs:
                p.paragraph_format.space_after = Pt(2)
                p.paragraph_format.space_before = Pt(2)
                for r in p.runs:
                    r.font.size = Pt(9.5)

    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # Parse and write markdown lines into stylized Word paragraphs and tables
    lines = minutes_text.splitlines()
    in_table = False
    table_lines = []

    for line in lines:
        stripped = line.strip()
        
        # Check if line is part of a markdown table
        if stripped.startswith("|") and stripped.endswith("|"):
            in_table = True
            table_lines.append(stripped)
            continue
        elif in_table:
            # End of table encountered: render table into doc
            render_markdown_table_to_docx(doc, table_lines)
            in_table = False
            table_lines = []

        if not stripped:
            continue

        if stripped.startswith("### "):
            h = doc.add_heading(level=2)
            h.paragraph_format.space_before = Pt(14)
            h.paragraph_format.space_after = Pt(4)
            add_markdown_runs(h, stripped[4:], Pt(13))
            for r in h.runs:
                r.font.size = Pt(13)
                r.font.bold = True
                r.font.color.rgb = RGBColor(0x2B, 0x6C, 0xB0)
        elif stripped.startswith("## "):
            h = doc.add_heading(level=1)
            h.paragraph_format.space_before = Pt(18)
            h.paragraph_format.space_after = Pt(6)
            add_markdown_runs(h, stripped[3:], Pt(15))
            for r in h.runs:
                r.font.size = Pt(15)
                r.font.bold = True
                r.font.color.rgb = RGBColor(0x1A, 0x36, 0x5D)
        elif stripped.startswith("- ") or stripped.startswith("* "):
            p = doc.add_paragraph(style='List Bullet')
            p.paragraph_format.space_after = Pt(3)
            add_markdown_runs(p, re.sub(r'^[-*]\s+', '', stripped))
        elif re.match(r'^\d+\.\s+', stripped):
            p = doc.add_paragraph(style='List Number')
            p.paragraph_format.space_after = Pt(3)
            add_markdown_runs(p, re.sub(r'^\d+\.\s+', '', stripped))
        else:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(4)
            add_markdown_runs(p, stripped)

    if in_table and table_lines:
        render_markdown_table_to_docx(doc, table_lines)

    # Append Raw Transcript if requested
    if raw_transcript and raw_transcript.strip():
        doc.add_page_break()
        h = doc.add_heading(level=1)
        r = h.add_run(_t("export.appendix", locale))
        r.font.size = Pt(15)
        r.font.color.rgb = RGBColor(0x1A, 0x36, 0x5D)
        
        for tline in raw_transcript.splitlines():
            if tline.strip():
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(2)
                add_markdown_runs(p, tline.strip(), Pt(9))
                for run in p.runs:
                    run.font.size = Pt(9)
                    run.font.color.rgb = RGBColor(0x4A, 0x55, 0x68)

    doc.save(file_path)
    return file_path

def render_markdown_table_to_docx(doc: Any, table_lines: list):
    """Parses markdown table lines and generates a styled docx table."""
    data_rows = []
    for line in table_lines:
        # Skip separator line like |---|---|
        if re.match(r'^\|[\s\-:|]+\|$', line):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if cells:
            data_rows.append(cells)

    if not data_rows:
        return

    num_cols = len(data_rows[0])
    tbl = doc.add_table(rows=len(data_rows), cols=num_cols)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = True

    for row_idx, row_data in enumerate(data_rows):
        is_header = (row_idx == 0)
        for col_idx, text in enumerate(row_data[:num_cols]):
            cell = tbl.cell(row_idx, col_idx)
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.space_after = Pt(3)
            add_markdown_runs(p, text, Pt(9.5) if is_header else Pt(9))
            
            if is_header:
                set_cell_background(cell, "2B6CB0") # Blue Header
                for r in p.runs:
                    r.font.bold = True
                    r.font.size = Pt(9.5)
                    r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            else:
                bg = "FFFFFF" if row_idx % 2 == 1 else "F7FAFC"
                set_cell_background(cell, bg)
                for r in p.runs:
                    r.font.size = Pt(9)

    doc.add_paragraph().paragraph_format.space_after = Pt(6)

def export_to_markdown(
    file_path: str,
    title: str,
    minutes_text: str,
    transcript: Optional[str] = None,
    locale: Optional[str] = None
) -> str:
    """Export formatted Markdown file."""
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    content = f"# {title}\n\n*Generated on: {stamp}*\n\n"
    content += minutes_text
    if transcript:
        content += (
            f"\n\n---\n\n## Full Audio Transcript\n\n"
            f"```text\n{transcript}\n```\n"
        )

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    return file_path

def strip_markdown_to_plain(text: str) -> str:
    """Convert a Markdown body into plain text with no Markdown syntax.

    - ATX headings become plain lines of the heading text.
    - Horizontal rules and blockquotes lose their markers.
    - Markdown tables become space-padded columns.
    - List markers are reduced to a simple '- '.
    - All inline Markdown is removed via strip_inline_markdown().
    """
    if not text:
        return ""

    out: list = []
    table_buf: list = []

    def flush_table() -> None:
        if not table_buf:
            return
        rows = []
        for line in table_buf:
            if re.match(r'^\|[\s\-:|]+\|$', line.strip()):
                continue
            rows.append([strip_inline_markdown(c.strip())
                         for c in line.strip().split("|")[1:-1]])
        table_buf.clear()
        if not rows:
            return
        widths = [max(len(r[i]) if i < len(r) else 0 for r in rows)
                  for i in range(max(len(r) for r in rows))]
        for idx, row in enumerate(rows):
            cells = [
                (row[i] if i < len(row) else "").ljust(widths[i])
                for i in range(len(widths))
            ]
            out.append("  ".join(cells).rstrip())
            if idx == 0:
                out.append("  ".join("-" * w for w in widths).rstrip())
        out.append("")

    for raw_line in text.splitlines():
        stripped = raw_line.strip()

        if stripped.startswith("|") and stripped.endswith("|"):
            table_buf.append(stripped)
            continue
        flush_table()

        if not stripped:
            out.append("")
            continue

        if re.match(r'^(?:-{3,}|\*{3,}|_{3,})$', stripped):
            out.append("")
            continue

        heading = re.match(r'^#{1,6}\s+(.*)$', stripped)
        if heading:
            content = strip_inline_markdown(heading.group(1)).strip()
            if content:
                out.append(content)
            continue

        if stripped.startswith(">"):
            out.append(strip_inline_markdown(stripped.lstrip("> ")))
            continue

        if stripped.startswith("```") or stripped.startswith("~~~"):
            continue

        if re.match(r'^[-*+]\s+', stripped):
            out.append("- " + strip_inline_markdown(re.sub(r'^[-*+]\s+', '', stripped)))
            continue

        if re.match(r'^\d+[.)]\s+', stripped):
            out.append("- " + strip_inline_markdown(re.sub(r'^\d+[.)]\s+', '', stripped)))
            continue

        out.append(strip_inline_markdown(stripped))

    flush_table()

    cleaned = "\n".join(out)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def export_to_text(
    file_path: str,
    title: str,
    minutes_text: str,
    transcript: Optional[str] = None,
    locale: Optional[str] = None
) -> str:
    """Export standard plain text file (no Markdown syntax)."""
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    bar = '=' * 60
    content = (
        f"{bar}\n{title.upper()}\n{bar}\n"
        f"{_t('export.generated_on', locale)}: {stamp}\n\n"
    )
    content += strip_markdown_to_plain(minutes_text)
    if transcript:
        content += (
            f"\n\n{bar}\nFULL AUDIO TRANSCRIPT\n{bar}\n\n"
            f"{strip_markdown_to_plain(transcript)}\n"
        )

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    return file_path
