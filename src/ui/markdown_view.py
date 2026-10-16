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
import textwrap
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
        """Format and print Markdown tables into neatly aligned multi-line column text."""
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

        num_cols = max(len(r) for r in rows)
        if num_cols == 0:
            return

        # Calculate max natural width across cells (splitting by <br>)
        natural_widths = [0] * num_cols
        for row_idx, r in enumerate(rows):
            if is_sep_row[row_idx]:
                continue
            for col_idx in range(num_cols):
                cell = r[col_idx] if col_idx < len(r) else ""
                parts = re.split(r"<br\s*/?>", cell, flags=re.I)
                for p in parts:
                    clean = re.sub(r"[*`]", "", p.strip())
                    natural_widths[col_idx] = max(natural_widths[col_idx], len(clean))

        # Minimum width based on header length or at least 4 characters
        header_row = rows[0] if rows else []
        min_widths = [
            max(4, len(re.sub(r"[*`]", "", header_row[c].strip()))) if c < len(header_row) else 4
            for c in range(num_cols)
        ]

        # Target available width for standard desktop text widget display (~112 chars)
        target_width = 112
        border_overhead = 4 + 3 * (num_cols - 1)
        avail_content_width = max(target_width - border_overhead, sum(min_widths))

        total_natural = sum(natural_widths)
        actual_widths = list(natural_widths)

        # Scale down large columns proportionally to fit target width with wrapping
        if total_natural > avail_content_width:
            small_cols = [c for c in range(num_cols) if natural_widths[c] <= 12]
            rem = avail_content_width - sum(natural_widths[c] for c in small_cols)
            flexible_cols = [c for c in range(num_cols) if c not in small_cols]
            flex_sum = sum(natural_widths[c] for c in flexible_cols)

            for c in range(num_cols):
                if c in small_cols:
                    actual_widths[c] = max(min_widths[c], natural_widths[c])
                else:
                    ratio = natural_widths[c] / flex_sum if flex_sum > 0 else (1.0 / len(flexible_cols))
                    allocated = int(rem * ratio)
                    actual_widths[c] = max(min_widths[c], allocated)
        else:
            actual_widths = [max(min_widths[c], natural_widths[c]) for c in range(num_cols)]

        def make_separator(left_ch: str, mid_ch: str, right_ch: str) -> str:
            sep_parts = ["─" * (actual_widths[c] + 2) for c in range(num_cols)]
            return left_ch + mid_ch.join(sep_parts) + right_ch + "\n"

        # Top border
        self.insert("end", make_separator("┌", "┬", "┐"), "table_sep")

        for row_idx, r in enumerate(rows):
            if is_sep_row[row_idx]:
                self.insert("end", make_separator("├", "┼", "┤"), "table_sep")
                continue

            # Break and word-wrap each cell into sublines
            cell_sublines: List[List[str]] = []
            for col_idx in range(num_cols):
                cell_raw = r[col_idx] if col_idx < len(r) else ""
                parts = re.split(r"<br\s*/?>", cell_raw, flags=re.I)
                wrapped_lines = []
                for part in parts:
                    clean_part = re.sub(r"[*`]", "", part.strip())
                    if not clean_part:
                        wrapped_lines.append("")
                    else:
                        sub_wrapped = textwrap.wrap(clean_part, width=actual_widths[col_idx])
                        wrapped_lines.extend(sub_wrapped if sub_wrapped else [""])
                cell_sublines.append(wrapped_lines if wrapped_lines else [""])

            max_lines_in_row = max(len(sl) for sl in cell_sublines)
            tag = "table_header" if row_idx == 0 else "table_row"

            for line_idx in range(max_lines_in_row):
                row_cells = []
                for col_idx in range(num_cols):
                    cell_val = cell_sublines[col_idx][line_idx] if line_idx < len(cell_sublines[col_idx]) else ""
                    row_cells.append(cell_val.ljust(actual_widths[col_idx]))
                self.insert("end", "│ " + " │ ".join(row_cells) + " │\n", tag)

            # Draw a subtle divider between table rows (except after header which already gets separator)
            if row_idx > 0 and row_idx < len(rows) - 1 and not is_sep_row[row_idx + 1]:
                self.insert("end", make_separator("├", "┼", "┤"), "table_sep")

        # Bottom border
        self.insert("end", make_separator("└", "┴", "┘"), "table_sep")
        self.insert("end", "\n")
