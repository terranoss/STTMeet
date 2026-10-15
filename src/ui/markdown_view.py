"""
STTMeet Markdown Viewer
Rich styled Markdown preview component for CustomTkinter textboxes.
Renders markdown elements into formatted Tkinter text tags:
- Headers (H1, H2, H3)
- Bold and Italic text
- Markdown tables with formatted aligned columns
- Bullet lists and Blockquotes
- Horizontal rules and key-value bold highlights
Supports toggling between formatted 'Preview' and 'Raw' Markdown.
"""
import re
import tkinter as tk
import customtkinter as ctk
from typing import Optional, List, Tuple


class MarkdownViewer(ctk.CTkTextbox):
    """
    A CustomTkinter CTkTextbox enhanced with rich markdown preview rendering.
    """
    def __init__(self, *args, **kwargs):
        # Set default font and line spacing for readable executive presentation
        if "font" not in kwargs:
            kwargs["font"] = ctk.CTkFont(family="Segoe UI", size=12)
        super().__init__(*args, **kwargs)

        self._raw_markdown = ""
        self._mode = "preview"  # "preview" or "raw"
        self._setup_tags()

    def _setup_tags(self):
        """Configure tags on the underlying tkinter Text widget for dark and light modes."""
        tb = self._textbox
        is_dark = ctk.get_appearance_mode() == "Dark"

        # Colors tailored for high contrast and executive polish
        h1_color = "#90CAF9" if is_dark else "#1565C0"
        h2_color = "#64B5F6" if is_dark else "#1976D2"
        h3_color = "#42A5F5" if is_dark else "#0D47A1"
        quote_color = "#B0BEC5" if is_dark else "#546E7A"
        table_hdr_color = "#80CBC4" if is_dark else "#00695C"
        hr_color = "#455A64" if is_dark else "#CFD8DC"
        bullet_color = "#81C784" if is_dark else "#2E7D32"

        # Tag configurations
        tb.tag_configure("h1", font=("Segoe UI", 18, "bold"), foreground=h1_color, spacing1=14, spacing3=6)
        tb.tag_configure("h2", font=("Segoe UI", 14, "bold"), foreground=h2_color, spacing1=12, spacing3=4)
        tb.tag_configure("h3", font=("Segoe UI", 12, "bold"), foreground=h3_color, spacing1=8, spacing3=2)
        tb.tag_configure("bold", font=("Segoe UI", 11, "bold"))
        tb.tag_configure("italic", font=("Segoe UI", 11, "italic"))
        tb.tag_configure("bold_italic", font=("Segoe UI", 11, "bold italic"))
        tb.tag_configure("blockquote", font=("Segoe UI", 11, "italic"), foreground=quote_color, lmargin1=20, lmargin2=20, spacing1=4, spacing3=4)
        tb.tag_configure("bullet", font=("Segoe UI", 11), lmargin1=16, lmargin2=28, spacing1=2, spacing3=2)
        tb.tag_configure("bullet_symbol", font=("Segoe UI", 11, "bold"), foreground=bullet_color)
        tb.tag_configure("table_header", font=("Consolas", 11, "bold"), foreground=table_hdr_color)
        tb.tag_configure("table_row", font=("Consolas", 11))
        tb.tag_configure("table_sep", font=("Consolas", 11), foreground=hr_color)
        tb.tag_configure("hr", font=("Segoe UI", 6), foreground=hr_color, spacing1=6, spacing3=6)
        tb.tag_configure("body", font=("Segoe UI", 11), spacing1=2, spacing3=2)
        tb.tag_configure("raw", font=("Consolas", 11))

    def delete(self, index1, index2=None):
        if str(index1) == "1.0" and (index2 is None or str(index2).lower() in ("end", "end-1c")):
            self._raw_markdown = ""
        super().delete(index1, index2)

    def set_markdown(self, markdown_text: str):
        """Set the markdown content and render based on current mode."""
        self._raw_markdown = markdown_text or ""
        self._refresh()

    def get_markdown(self) -> str:
        """Retrieve the raw markdown text."""
        return self._raw_markdown

    def set_view_mode(self, mode: str):
        """Switch between 'preview' and 'raw' mode."""
        if mode in ("preview", "raw"):
            self._mode = mode
            self._refresh()

    def get_view_mode(self) -> str:
        return self._mode

    def _refresh(self):
        """Re-render the textbox content."""
        self._setup_tags()
        super().delete("1.0", "end")

        if not self._raw_markdown.strip():
            return

        if self._mode == "raw":
            self.insert("1.0", self._raw_markdown, "raw")
        else:
            self._render_markdown(self._raw_markdown)

    def _render_markdown(self, text: str):
        """Parse and stream formatted text into Tk Text widget with appropriate tags."""
        lines = text.splitlines()
        i = 0
        total_lines = len(lines)

        while i < total_lines:
            line = lines[i]
            stripped = line.strip()

            # Empty lines
            if not stripped:
                self.insert("end", "\n")
                i += 1
                continue

            # Markdown Table detection
            if stripped.startswith("|") and stripped.endswith("|"):
                # Collect contiguous table lines
                table_lines = []
                while i < total_lines and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                    table_lines.append(lines[i].strip())
                    i += 1
                self._render_table(table_lines)
                continue

            # Headers
            if stripped.startswith("### "):
                self.insert("end", stripped[4:] + "\n", "h3")
                i += 1
                continue
            elif stripped.startswith("## "):
                self.insert("end", stripped[3:] + "\n", "h2")
                i += 1
                continue
            elif stripped.startswith("# "):
                self.insert("end", stripped[2:] + "\n", "h1")
                i += 1
                continue

            # Horizontal Rule
            if stripped in ("---", "***", "___"):
                self.insert("end", "―" * 55 + "\n", "hr")
                i += 1
                continue

            # Blockquote
            if stripped.startswith("> "):
                self.insert("end", "▎ " + stripped[2:] + "\n", "blockquote")
                i += 1
                continue

            # Bullet List Item
            if stripped.startswith(("* ", "- ", "• ")):
                content = stripped[2:]
                self.insert("end", "  • ", "bullet_symbol")
                self._render_inline_spans(content, base_tag="bullet")
                self.insert("end", "\n")
                i += 1
                continue

            # Numbered List Item
            num_match = re.match(r"^(\d+\.)\s+(.+)$", stripped)
            if num_match:
                prefix = num_match.group(1)
                content = num_match.group(2)
                self.insert("end", f"  {prefix} ", "bullet_symbol")
                self._render_inline_spans(content, base_tag="bullet")
                self.insert("end", "\n")
                i += 1
                continue

            # Standard body paragraph
            self._render_inline_spans(line, base_tag="body")
            self.insert("end", "\n")
            i += 1

    def _render_inline_spans(self, text: str, base_tag: str = "body"):
        """Render inline **bold**, *italic*, and `code` styling within a line."""
        # Pattern to split by bold, italic, bold-italic, or inline code
        pattern = re.compile(r"(\*\*\*[^*]+\*\*\*|\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)")
        tokens = pattern.split(text)

        for token in tokens:
            if not token:
                continue
            if token.startswith("***") and token.endswith("***") and len(token) > 6:
                self.insert("end", token[3:-3], (base_tag, "bold_italic"))
            elif token.startswith("**") and token.endswith("**") and len(token) > 4:
                self.insert("end", token[2:-2], (base_tag, "bold"))
            elif token.startswith("*") and token.endswith("*") and len(token) > 2:
                self.insert("end", token[1:-1], (base_tag, "italic"))
            elif token.startswith("`") and token.endswith("`") and len(token) > 2:
                self.insert("end", token[1:-1], (base_tag, "raw"))
            else:
                self.insert("end", token, base_tag)

    def _render_table(self, table_lines: List[str]):
        """Format and print Markdown tables into neatly aligned column text."""
        if not table_lines:
            return

        rows: List[List[str]] = []
        is_sep_row = []

        for line in table_lines:
            cells = [c.strip() for c in line.strip("|").split("|")]
            is_sep = all(re.match(r"^:?-+:?$", c) for c in cells if c)
            is_sep_row.append(is_sep)
            rows.append(cells)

        if not rows:
            return

        # Determine column count and max length per column
        num_cols = max(len(r) for r in rows)
        col_widths = [0] * num_cols

        for row_idx, r in enumerate(rows):
            if is_sep_row[row_idx]:
                continue
            for col_idx, cell in enumerate(r):
                # Clean markdown bold/italic tags when computing visible cell width
                clean_cell = re.sub(r"[*`]", "", cell)
                if len(clean_cell) > col_widths[col_idx]:
                    col_widths[col_idx] = len(clean_cell)

        # Cap max column width to keep display bounded
        col_widths = [max(min(w, 40), 4) for w in col_widths]

        # Render rows
        for row_idx, r in enumerate(rows):
            if is_sep_row[row_idx]:
                # Draw separator line
                sep_parts = ["─" * (col_widths[c] + 2) for c in range(min(len(r), num_cols))]
                self.insert("end", "├" + "┼".join(sep_parts) + "┤\n", "table_sep")
                continue

            row_cells = []
            for col_idx in range(num_cols):
                raw_val = r[col_idx] if col_idx < len(r) else ""
                clean_val = re.sub(r"[*`]", "", raw_val)
                # Left align and pad
                padded = clean_val[:col_widths[col_idx]].ljust(col_widths[col_idx])
                row_cells.append(padded)

            tag = "table_header" if row_idx == 0 else "table_row"
            self.insert("end", "│ " + " │ ".join(row_cells) + " │\n", tag)

        self.insert("end", "\n")
