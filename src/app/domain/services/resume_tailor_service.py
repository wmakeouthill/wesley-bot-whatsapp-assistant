from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class StyledLine:
    text: str
    font: str
    size: int
    indent: int = 0
    spacing_after: int = 0


class ResumeTailorService:
    def markdown_to_styled_lines(self, markdown_content: str) -> List[StyledLine]:
        lines: List[StyledLine] = []
        for raw_line in markdown_content.splitlines():
            line = raw_line.strip()
            if not line:
                lines.append(StyledLine("", "F1", 10, spacing_after=4))
                continue
            if line.startswith("### "):
                lines.append(StyledLine(line[4:].upper(), "F2", 12, spacing_after=2))
            elif line.startswith("## "):
                lines.append(StyledLine(line[3:].upper(), "F2", 14, spacing_after=4))
            elif line.startswith("# "):
                lines.append(StyledLine(line[2:].upper(), "F2", 18, spacing_after=8))
            elif line.startswith("- "):
                lines.append(StyledLine(f"• {self._clean_inline_markdown(line[2:])}", "F1", 10, indent=18, spacing_after=1))
            else:
                cleaned = self._clean_inline_markdown(line)
                if cleaned:
                    lines.append(StyledLine(cleaned, "F1", 10, spacing_after=2))
        return lines

    def markdown_to_pdf_bytes(self, markdown_content: str, title: str = "Curriculo Personalizado") -> bytes:
        lines = self.markdown_to_styled_lines(markdown_content)
        if not lines or lines[0].font != "F2":
            lines = [StyledLine(title.upper(), "F2", 18, spacing_after=8)] + lines
        wrapped = self._wrap_lines(lines)
        return self._build_simple_pdf(wrapped)

    def _wrap_lines(self, lines: List[StyledLine]) -> List[StyledLine]:
        wrapped: List[StyledLine] = []
        for line in lines:
            max_chars = self._max_chars_for_style(line)
            if len(line.text) <= max_chars:
                wrapped.append(line)
                continue
            words = line.text.split()
            current = ""
            for word in words:
                candidate = word if not current else f"{current} {word}"
                if len(candidate) <= max_chars:
                    current = candidate
                else:
                    if current:
                        wrapped.append(
                            StyledLine(current, line.font, line.size, line.indent, spacing_after=0)
                        )
                    current = word
            if current:
                wrapped.append(
                    StyledLine(current, line.font, line.size, line.indent, spacing_after=line.spacing_after)
                )
        return wrapped

    def _escape_pdf_text(self, text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def _build_simple_pdf(self, lines: List[StyledLine]) -> bytes:
        page_width = 612
        page_height = 792
        margin_x = 45
        margin_top = 740
        bottom_margin = 60

        pages: list[list[StyledLine]] = [[]]
        current_y = margin_top
        for line in lines:
            required_height = max(line.size + 4 + line.spacing_after, 14)
            if current_y - required_height < bottom_margin:
                pages.append([])
                current_y = margin_top
            pages[-1].append(line)
            current_y -= required_height

        objects: list[bytes] = []
        page_object_numbers: list[int] = []
        next_object_number = 3  # 1 catalog, 2 pages root

        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        font_regular_object_number = next_object_number
        next_object_number += 1
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
        font_bold_object_number = next_object_number
        next_object_number += 1

        for page_lines in pages:
            content_lines = ["BT"]
            current_y = margin_top
            for line in page_lines:
                font_ref = line.font
                escaped = self._escape_pdf_text(line.text)
                current_x = margin_x + line.indent
                content_lines.append(f"/{font_ref} {line.size} Tf")
                content_lines.append(f"1 0 0 1 {current_x} {current_y} Tm")
                content_lines.append(f"({escaped}) Tj")
                current_y -= max(line.size + 4 + line.spacing_after, 14)
            content_lines.append("ET")
            content_stream = "\n".join(content_lines).encode("latin-1", errors="replace")
            content_object = f"<< /Length {len(content_stream)} >>\nstream\n".encode("ascii") + content_stream + b"\nendstream"
            content_object_number = next_object_number
            objects.append(content_object)
            next_object_number += 1

            page_object = (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
                f"/Resources << /Font << /F1 {font_regular_object_number} 0 R /F2 {font_bold_object_number} 0 R >> >> "
                f"/Contents {content_object_number} 0 R >>"
            ).encode("ascii")
            page_object_number = next_object_number
            objects.append(page_object)
            page_object_numbers.append(page_object_number)
            next_object_number += 1

        kids = " ".join(f"{num} 0 R" for num in page_object_numbers)
        pages_root = f"<< /Type /Pages /Count {len(page_object_numbers)} /Kids [{kids}] >>".encode("ascii")
        catalog = b"<< /Type /Catalog /Pages 2 0 R >>"

        full_objects: list[tuple[int, bytes]] = [(1, catalog), (2, pages_root)]
        full_objects.extend((idx + 3, obj) for idx, obj in enumerate(objects))

        pdf = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for obj_num, obj_bytes in full_objects:
            offsets.append(len(pdf))
            pdf.extend(f"{obj_num} 0 obj\n".encode("ascii"))
            pdf.extend(obj_bytes)
            pdf.extend(b"\nendobj\n")

        xref_offset = len(pdf)
        pdf.extend(f"xref\n0 {len(full_objects) + 1}\n".encode("ascii"))
        pdf.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

        pdf.extend(
            (
                f"trailer\n<< /Size {len(full_objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF"
            ).encode("ascii")
        )
        return bytes(pdf)

    def _clean_inline_markdown(self, line: str) -> str:
        return (
            line.replace("**", "")
            .replace("__", "")
            .replace("`", "")
            .replace("[", "")
            .replace("]", "")
        )

    def _max_chars_for_style(self, line: StyledLine) -> int:
        if line.font == "F2" and line.size >= 18:
            return 42
        if line.font == "F2":
            return 60
        if line.indent:
            return 82
        return 95
