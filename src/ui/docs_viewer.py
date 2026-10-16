"""
STTMeet Documentation Viewer
In-app reader for the bundled docs/ folder.

Presents a curated list of documents in a sidebar and renders the selected one
with the shared MarkdownViewer widget, so the user guide and the meeting minute
format guide are readable without leaving the application.

Plain-text documents listed in DESCRIPTIVE_DOCS (the meeting minute format
descriptions) are structured into Markdown before rendering, so the prose in
the source file stays readable despite being stored as one continuous block.
"""
import re
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import customtkinter as ctk

from ..config import DOCS_DIR
from ..i18n import has_key, translate
from .markdown_view import MarkdownViewer
from .theme import (
    ACCENT_FG,
    ACCENT_HOVER,
    ACCENT_TEXT,
    MUTED_TEXT,
    SIDEBAR_BORDER,
    SIDEBAR_FG,
    TRANSPARENT_HOVER,
    TRANSPARENT_TEXT,
)


SIDEBAR_WIDTH = 220

# Curated reading order. Only these files appear in the sidebar, so adding a
# new file to docs/ never silently changes the reader.
DOC_ORDER: Tuple[str, ...] = (
    "user_guide.md",
    "meeting_minute/template_descp.txt",
    "executive_meeting_recap_template.md",
)

# Documents stored as prose that must be structured into Markdown on the fly.
DESCRIPTIVE_DOCS: Tuple[str, ...] = ("meeting_minute/template_descp.txt",)

_SHORT_LABEL = re.compile(r"Short\s+Description\s*:", re.I)
_EXPLANATION_LABEL = re.compile(r"Explanation\s*:", re.I)
_SECTION_START = re.compile(r"(?:^|\s)(\d+)\.\s*(.+?)\s*Template\s*Short Description\s*:", re.I)


class TemplateDescription:
    """One meeting minute format: its name, one-liner and full explanation."""

    def __init__(self, number: int, name: str, short: str, explanation: str):
        self.number = number
        self.name = name
        self.short = short
        self.explanation = explanation


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_template_descriptions(text: str) -> List[TemplateDescription]:
    """Split the run-on format description file into one entry per format."""
    matches = list(_SECTION_START.finditer(text or ""))
    if not matches:
        return []

    entries: List[TemplateDescription] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end]

        short_split = _SHORT_LABEL.split(body, maxsplit=1)
        tail = short_split[1] if len(short_split) > 1 else body
        explanation_split = _EXPLANATION_LABEL.split(tail, maxsplit=1)
        short = _clean(explanation_split[0]) if len(explanation_split) > 1 else ""
        explanation = _clean(explanation_split[1]) if len(explanation_split) > 1 else ""

        entries.append(TemplateDescription(
            number=int(match.group(1)),
            name=_clean(match.group(2)),
            short=short,
            explanation=explanation,
        ))
    return entries


def template_descriptions_markdown(text: str, locale: str = "en") -> str:
    """Render the format description file as Markdown for the preview pane."""
    entries = parse_template_descriptions(text)
    lines = [f"# {translate('docs.formats.heading', locale)}", ""]

    if not entries:
        lines.append(_clean(text))
        return "\n".join(lines)

    lines.append(translate("docs.formats.lead", locale))
    lines.append("")
    for entry in entries:
        lines.append(f"## {entry.number}. {entry.name}")
        lines.append("")
        if entry.short:
            lines.append(f"**{translate('docs.formats.short', locale)}** {entry.short}")
            lines.append("")
        if entry.explanation:
            lines.append(f"**{translate('docs.formats.explanation', locale)}** {entry.explanation}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _slug(rel_path: str) -> str:
    stem = Path(rel_path).with_suffix("").as_posix()
    return stem.replace("/", ".").replace("\\", ".").replace("-", "_")


def discover_documents(docs_dir: Optional[Path] = None) -> List[str]:
    """Return the curated documents that actually exist under docs_dir."""
    root = Path(docs_dir) if docs_dir is not None else DOCS_DIR
    if not root.is_dir():
        return []
    return [rel for rel in DOC_ORDER if (root / rel).is_file()]


def document_title(rel_path: str, text: str, locale: str) -> str:
    """Localized sidebar title, falling back to the document's first heading."""
    key = f"docs.doc.{_slug(rel_path)}"
    if has_key(key):
        return translate(key, locale)
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped:
            break
    return Path(rel_path).stem.replace("_", " ").title()


class DocsWindow(ctk.CTkToplevel):
    """Modal-less window listing the bundled docs and rendering the selected one."""

    def __init__(self, master, locale: str = "ms", on_close: Optional[Callable] = None):
        super().__init__(master)
        self.title(translate("docs.window.title", locale))
        self.geometry("980x660")
        self.minsize(760, 480)
        self.transient(master)

        self._locale = locale
        self._on_close = on_close
        self._docs = discover_documents()
        self._active_rel: Optional[str] = None
        self._buttons: List[Tuple[str, ctk.CTkButton]] = []

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkScrollableFrame(
            self,
            width=SIDEBAR_WIDTH,
            corner_radius=0,
            fg_color=SIDEBAR_FG,
            border_width=1,
            border_color=SIDEBAR_BORDER
        )
        self.sidebar.grid(row=0, column=0, sticky="nsw")

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=14, pady=14)
        self.content.grid_rowconfigure(1, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.heading = ctk.CTkLabel(
            self.content,
            text="",
            anchor="w",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.heading.grid(row=0, column=0, pady=(0, 8), sticky="ew")

        self.viewer = MarkdownViewer(self.content, wrap="word")
        self.viewer.grid(row=1, column=0, sticky="nsew")

        self.status = ctk.CTkLabel(
            self.content,
            text="",
            anchor="w",
            text_color=MUTED_TEXT,
            font=ctk.CTkFont(size=11)
        )
        self.status.grid(row=2, column=0, pady=(8, 0), sticky="ew")

        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build_sidebar()

        if self._docs:
            self._select(self._docs[0])
        else:
            self._show_missing()

    # ------------------------------------------------------------------ build

    def _build_sidebar(self):
        heading = ctk.CTkLabel(
            self.sidebar,
            text=translate("docs.sidebar.title", self._locale),
            anchor="w",
            padx=14,
            pady=12,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=MUTED_TEXT
        )
        heading.grid(row=0, column=0, padx=6, sticky="ew")

        holder = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        holder.grid(row=1, column=0, padx=6, sticky="nsew")
        holder.grid_columnconfigure(0, weight=1)

        self._buttons.clear()
        for rel_path in self._docs:
            text = self._read(rel_path)
            btn = ctk.CTkButton(
                holder,
                text=document_title(rel_path, text, self._locale),
                anchor="w",
                width=SIDEBAR_WIDTH - 32,
                height=34,
                corner_radius=0,
                fg_color="transparent",
                text_color=TRANSPARENT_TEXT,
                hover_color=TRANSPARENT_HOVER,
                font=ctk.CTkFont(size=12),
                command=lambda r=rel_path: self._select(r)
            )
            btn.grid(row=len(self._buttons), column=0, pady=1, sticky="ew")
            self._buttons.append((rel_path, btn))

    def _read(self, rel_path: str) -> str:
        """Raw file contents, used for the sidebar title fallback."""
        try:
            return (DOCS_DIR / rel_path).read_text(encoding="utf-8")
        except OSError:
            return ""

    def _render(self, rel_path: str) -> str:
        """Display text for a document, structured if it is stored as prose."""
        raw = self._read(rel_path)
        if rel_path in DESCRIPTIVE_DOCS:
            return template_descriptions_markdown(raw, self._locale)
        return raw

    # ----------------------------------------------------------------- render

    def _select(self, rel_path: str):
        self._active_rel = rel_path
        self.heading.configure(
            text=document_title(rel_path, self._render(rel_path), self._locale)
        )
        self.viewer.set_markdown(self._render(rel_path))
        self.status.configure(text=translate("docs.source", self._locale, path=f"docs/{rel_path}"))
        self._highlight()

    def _show_missing(self):
        self.heading.configure(text=translate("docs.window.title", self._locale))
        self.viewer.set_markdown("")
        self.status.configure(text=translate("docs.missing", self._locale))

    def _highlight(self):
        for rel_path, btn in self._buttons:
            active = rel_path == self._active_rel
            btn.configure(
                fg_color=ACCENT_FG if active else "transparent",
                text_color=ACCENT_TEXT if active else TRANSPARENT_TEXT,
                hover_color=ACCENT_HOVER if active else TRANSPARENT_HOVER,
                font=ctk.CTkFont(size=12, weight="bold" if active else "normal")
            )

    # ---------------------------------------------------------------- control

    def refresh_locale(self, locale: str):
        """Re-label the window after a UI language switch, keeping the open page."""
        self._locale = locale
        self.title(translate("docs.window.title", locale))
        active = self._active_rel
        for child in self.sidebar.winfo_children():
            child.destroy()
        self._build_sidebar()
        if active and active in self._docs:
            self._select(active)
        elif self._docs:
            self._select(self._docs[0])
        else:
            self._show_missing()

    def _close(self):
        if self._on_close:
            self._on_close(self)
        self.destroy()
