from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False


@dataclass(frozen=True)
class ResumeSection:
    title: str
    items: list[str]


class ResumeTailorService:
    def __init__(self) -> None:
        self._font_regular = "Helvetica"
        self._font_bold = "Helvetica-Bold"
        if REPORTLAB_AVAILABLE:
            self._register_fonts()

    def markdown_to_pdf_bytes(self, markdown_content: str, title: str = "Curriculo Personalizado") -> bytes:
        if not REPORTLAB_AVAILABLE:
            return self._fallback_pdf_bytes(markdown_content, title)

        name, contact_lines, sections = self._parse_markdown(markdown_content, title)
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            topMargin=16 * mm,
            bottomMargin=14 * mm,
            title=title,
        )
        styles = self._build_styles()
        story = []

        story.append(Paragraph(self._escape(name), styles["name"]))
        if contact_lines:
            story.append(Spacer(1, 4))
            story.append(Paragraph(self._escape(" | ".join(contact_lines)), styles["contact"]))
        story.append(Spacer(1, 10))
        story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#274060")))
        story.append(Spacer(1, 10))

        for section in sections:
            story.append(Paragraph(self._escape(section.title), styles["section"]))
            story.append(Spacer(1, 3))
            for item in section.items:
                kind, text = self._classify_item(item)
                if kind == "subheading":
                    story.append(Paragraph(self._escape(text), styles["subheading"]))
                elif kind == "period":
                    story.append(Paragraph(self._escape(text), styles["period"]))
                elif kind == "bullet":
                    story.append(Paragraph(self._bullet_html(text), styles["bullet"]))
                else:
                    story.append(Paragraph(self._escape(text), styles["body"]))
            story.append(Spacer(1, 8))

        doc.build(story)
        return buffer.getvalue()

    def _parse_markdown(self, markdown_content: str, fallback_title: str) -> tuple[str, list[str], list[ResumeSection]]:
        lines = [line.rstrip() for line in markdown_content.splitlines()]
        name = fallback_title
        contact_lines: list[str] = []
        sections: list[ResumeSection] = []
        current_section: Optional[ResumeSection] = None
        in_contact = False

        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("# "):
                name = self._clean_inline_markdown(line[2:])
                continue
            if line.startswith("## "):
                title = self._clean_inline_markdown(line[3:])
                if title.upper() in {"CONTATO", "CONTACT"}:
                    in_contact = True
                    current_section = None
                    continue
                in_contact = False
                current_section = ResumeSection(title=title, items=[])
                sections.append(current_section)
                continue
            if in_contact:
                if line.startswith("- "):
                    contact_lines.append(self._clean_inline_markdown(line[2:]))
                else:
                    contact_lines.append(self._clean_inline_markdown(line))
                continue
            if current_section is None:
                continue
            if line.startswith("### "):
                current_section.items.append(f"### {self._clean_inline_markdown(line[4:])}")
            elif line.startswith("*") and line.endswith("*"):
                current_section.items.append(f"*{self._clean_inline_markdown(line.strip('*'))}*")
            elif line.startswith("- "):
                current_section.items.append(f"- {self._clean_inline_markdown(line[2:])}")
            else:
                current_section.items.append(self._clean_inline_markdown(line))

        return name, contact_lines, sections

    def _classify_item(self, item: str) -> tuple[str, str]:
        if item.startswith("### "):
            return "subheading", item[4:]
        if item.startswith("*") and item.endswith("*"):
            return "period", item.strip("*")
        if item.startswith("- "):
            return "bullet", item[2:]
        return "body", item

    def _build_styles(self):
        stylesheet = getSampleStyleSheet()
        return {
            "name": ParagraphStyle(
                "ResumeName",
                parent=stylesheet["Heading1"],
                fontName=self._font_bold,
                fontSize=22,
                leading=26,
                textColor=colors.HexColor("#1F2D3D"),
                alignment=TA_CENTER,
                spaceAfter=2,
            ),
            "contact": ParagraphStyle(
                "ResumeContact",
                parent=stylesheet["BodyText"],
                fontName=self._font_regular,
                fontSize=9.5,
                leading=12,
                alignment=TA_CENTER,
                textColor=colors.HexColor("#425466"),
            ),
            "section": ParagraphStyle(
                "ResumeSection",
                parent=stylesheet["Heading2"],
                fontName=self._font_bold,
                fontSize=12.5,
                leading=16,
                textColor=colors.HexColor("#274060"),
                spaceBefore=4,
                spaceAfter=5,
            ),
            "subheading": ParagraphStyle(
                "ResumeSubheading",
                parent=stylesheet["Heading3"],
                fontName=self._font_bold,
                fontSize=10.8,
                leading=14,
                textColor=colors.HexColor("#1F2D3D"),
                spaceBefore=3,
                spaceAfter=1,
            ),
            "period": ParagraphStyle(
                "ResumePeriod",
                parent=stylesheet["Italic"],
                fontName=self._font_regular,
                fontSize=9.3,
                leading=12,
                textColor=colors.HexColor("#6B7280"),
                leftIndent=4,
                spaceAfter=3,
            ),
            "body": ParagraphStyle(
                "ResumeBody",
                parent=stylesheet["BodyText"],
                fontName=self._font_regular,
                fontSize=9.8,
                leading=13,
                textColor=colors.HexColor("#1F2937"),
                spaceAfter=3,
            ),
            "bullet": ParagraphStyle(
                "ResumeBullet",
                parent=stylesheet["BodyText"],
                fontName=self._font_regular,
                fontSize=9.7,
                leading=13,
                leftIndent=12,
                firstLineIndent=0,
                bulletIndent=0,
                textColor=colors.HexColor("#1F2937"),
                spaceAfter=2,
            ),
        }

    def _register_fonts(self) -> None:
        candidates = [
            (
                "ResumeSans",
                "ResumeSansBold",
                [
                    (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
                    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
                    (Path("/usr/share/fonts/TTF/DejaVuSans.ttf"), Path("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf")),
                ],
            ),
        ]
        for regular_name, bold_name, paths in candidates:
            for regular_path, bold_path in paths:
                if regular_path.exists() and bold_path.exists():
                    pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))
                    pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
                    self._font_regular = regular_name
                    self._font_bold = bold_name
                    return

    def _clean_inline_markdown(self, text: str) -> str:
        cleaned = (
            text.replace("**", "")
            .replace("__", "")
            .replace("`", "")
            .replace("[", "")
            .replace("]", "")
            .replace("—", "-")
            .replace("–", "-")
            .replace("•", "-")
            .replace("→", "->")
        )
        return " ".join(cleaned.split())

    def _bullet_html(self, text: str) -> str:
        return f"&bull;&nbsp;{self._escape(text)}"

    def _escape(self, text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _fallback_pdf_bytes(self, markdown_content: str, title: str) -> bytes:
        content = f"{title}\n\n{markdown_content}".encode("cp1252", errors="replace")
        return b"%PDF-1.4\n% fallback\n" + content
