from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape
from io import BytesIO
import logging
from pathlib import Path
import re
import unicodedata
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.styles import ParagraphStyle, StyleSheet1, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    CondPageBreak,
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..analysis.interface import SectionDraft


logger = logging.getLogger(__name__)

REPORT_RENDERER_VERSION = "REPORTLAB-TTF-V4"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_FONT_DIR = PROJECT_ROOT / "assets" / "fonts"
BRAND_LOGO_PATH = PROJECT_ROOT / "assets" / "brand" / "mySUNI.png"
NANUM_REGULAR_FONT_PATH = PROJECT_FONT_DIR / "NanumGothic-Regular.ttf"
NANUM_BOLD_FONT_PATH = PROJECT_FONT_DIR / "NanumGothic-Bold.ttf"
REPORT_FONT_FAMILY = "MyWikiReportFont"
REPORT_FONT_REGULAR = f"{REPORT_FONT_FAMILY}-Regular"
REPORT_FONT_BOLD = f"{REPORT_FONT_FAMILY}-Bold"
NAVY = colors.HexColor("#0F172A")
SLATE = colors.HexColor("#475569")
BORDER = colors.HexColor("#CBD5E1")
LIGHT_BORDER = colors.HexColor("#E2E8F0")
PALE = colors.HexColor("#F8FAFC")
ACCENT = colors.HexColor("#F97316")
DARK_TEXT = colors.HexColor("#111827")

K_TITLE = "\uc77c\uc77c \uc0b0\uc5c5 \ub3d9\ud5a5 \ubcf4\uace0\uc11c"
K_EXECUTIVE = "\uc624\ub298\uc758 \ud575\uc2ec \uc694\uc57d"
K_ISSUES = "\uc774\uc288\ubcc4 \ubd84\uc11d"
K_FACTS = "\uc0ac\uc2e4"
K_MEANING = "\uc758\ubbf8"
K_IMPACT = "SK\ud558\uc774\ub2c9\uc2a4 \uc601\ud5a5"
K_WATCH = "\ub2e4\uc74c \ud655\uc778 \uc0ac\ud56d"
K_SOURCES = "\ucd9c\ucc98"
K_CATEGORIES = "\uce74\ud14c\uace0\ub9ac\ubcc4 \uc815\ub9ac"
K_IMPLICATIONS = "\uc885\ud569 \uc2dc\uc0ac\uc810"
K_OPPORTUNITY = "\uae30\ud68c"
K_RISK = "\uc704\ud5d8"
K_MONITORING = "\uc9c0\uc18d \uad00\ucc30"
K_ALL_SOURCES = "\uc804\uccb4 \ucd9c\ucc98 \ubaa9\ub85d"
K_NO_TRENDS = "\uc8fc\uc694 \ub3d9\ud5a5 \uc5c6\uc74c"
K_NO_INFORMATION = "\uc815\ubcf4 \uc5c6\uc74c"
K_DAILY_BRIEF_EN = "DAILY INDUSTRY BRIEF"
K_NEXT_WATCH_EN = "NEXT WATCH"


@dataclass(frozen=True)
class PdfLayout:
    page_size: str = "A4"
    orientation: str = "portrait"
    margin_mm: int = 19
    top_margin_mm: int = 24
    bottom_margin_mm: int = 20
    title_font_size: int = 22
    heading_font_size: int = 14
    body_font_size: float = 10.0
    line_height: float = 1.35
    max_evidences_per_section: int = 3


@dataclass(frozen=True)
class PdfEvidenceLine:
    document_version_id: str
    quoted_text: str
    relevance_score: Optional[float] = None


@dataclass(frozen=True)
class PdfSourceLine:
    source_type: str
    source_name: str
    title: str
    published_at: str = ""
    url: str | None = None


@dataclass(frozen=True)
class PdfExecutiveSummaryLine:
    title: str
    summary: str
    category: str = ""
    importance_score: int | None = None
    impact_direction: str = ""
    time_horizon: str = ""


@dataclass(frozen=True)
class PdfSection:
    category: str
    title: str
    body: str
    confidence_label: str
    evidences: tuple[PdfEvidenceLine, ...] = ()
    section_type: str = "content"
    importance_score: int | None = None
    reliability_score: int | None = None
    impact_direction: str = ""
    time_horizon: str = ""
    source_rows: tuple[PdfSourceLine, ...] = ()
    executive_items: tuple[PdfExecutiveSummaryLine, ...] = ()


@dataclass(frozen=True)
class PdfReportDocument:
    title: str
    subtitle: str
    generated_at: str
    version: int | None
    layout: PdfLayout = field(default_factory=PdfLayout)
    sections: tuple[PdfSection, ...] = ()


DEFAULT_DAILY_REPORT_LAYOUT = PdfLayout()


def normalize_pdf_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value or "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    sanitized: list[str] = []
    for char in normalized:
        codepoint = ord(char)
        if char in {"\u2713", "\u2714", "\u2611", "\u2705"}:
            sanitized.append("[check]")
        elif 0x1F300 <= codepoint <= 0x1FAFF:
            sanitized.append("[emoji]")
        elif unicodedata.category(char) == "Cs":
            sanitized.append("?")
        else:
            sanitized.append(char)
    return "".join(sanitized)


def build_daily_report_pdf_document(
    *,
    report_key: str,
    version: int,
    sections: list[SectionDraft],
    generated_at: Optional[str] = None,
    layout: PdfLayout = DEFAULT_DAILY_REPORT_LAYOUT,
) -> PdfReportDocument:
    completed_sections = [
        _to_pdf_section(section, max_evidences=layout.max_evidences_per_section)
        for section in sections
        if section.status == "completed"
    ]
    return PdfReportDocument(
        title=normalize_pdf_text(f"Daily Trend Report {REPORT_RENDERER_VERSION}"),
        subtitle=normalize_pdf_text(report_key),
        generated_at=normalize_pdf_text(generated_at or _utc_now_iso()),
        version=version,
        layout=layout,
        sections=tuple(completed_sections),
    )


def render_daily_report_pdf(document: PdfReportDocument) -> bytes:
    normalized_document = _normalize_document(document)
    _log_document_preview(normalized_document)
    _register_report_fonts()
    layout = normalized_document.layout
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=_resolve_page_size(layout),
        leftMargin=layout.margin_mm * mm,
        rightMargin=layout.margin_mm * mm,
        topMargin=layout.top_margin_mm * mm,
        bottomMargin=layout.bottom_margin_mm * mm,
        title=normalized_document.title,
        author="myWiki",
    )
    doc.build(
        _build_story(normalized_document, _build_styles(layout)),
        onFirstPage=lambda page_canvas, pdf_doc: _draw_page_header(page_canvas, pdf_doc, normalized_document, layout),
        onLaterPages=lambda page_canvas, pdf_doc: _draw_page_header(page_canvas, pdf_doc, normalized_document, layout),
        canvasmaker=lambda *args, **kwargs: _NumberedCanvas(*args, document=normalized_document, layout=layout, **kwargs),
    )
    return buffer.getvalue()


def build_daily_report_pdf_filename(*, report_key: str, version: int) -> str:
    normalized_key = normalize_pdf_text(report_key).strip().replace(" ", "-")
    return f"{normalized_key}-v{version}.pdf"


def _normalize_document(document: PdfReportDocument) -> PdfReportDocument:
    return PdfReportDocument(
        title=normalize_pdf_text(document.title),
        subtitle=normalize_pdf_text(document.subtitle),
        generated_at=normalize_pdf_text(document.generated_at),
        version=document.version,
        layout=document.layout,
        sections=tuple(
            PdfSection(
                category=normalize_pdf_text(section.category),
                title=normalize_pdf_text(section.title),
                body=normalize_pdf_text(section.body),
                confidence_label=normalize_pdf_text(section.confidence_label),
                evidences=tuple(
                    PdfEvidenceLine(
                        document_version_id=normalize_pdf_text(item.document_version_id),
                        quoted_text=normalize_pdf_text(item.quoted_text),
                        relevance_score=item.relevance_score,
                    )
                    for item in section.evidences
                ),
                section_type=section.section_type,
                importance_score=section.importance_score,
                reliability_score=section.reliability_score,
                impact_direction=normalize_pdf_text(section.impact_direction),
                time_horizon=normalize_pdf_text(section.time_horizon),
                source_rows=tuple(
                    PdfSourceLine(
                        source_type=normalize_pdf_text(item.source_type),
                        source_name=normalize_pdf_text(item.source_name),
                        title=normalize_pdf_text(item.title),
                        published_at=normalize_pdf_text(item.published_at),
                        url=normalize_pdf_text(item.url) if item.url else None,
                    )
                    for item in section.source_rows
                ),
                executive_items=tuple(
                    PdfExecutiveSummaryLine(
                        title=normalize_pdf_text(item.title),
                        summary=normalize_pdf_text(item.summary),
                        category=normalize_pdf_text(item.category),
                        importance_score=item.importance_score,
                        impact_direction=normalize_pdf_text(item.impact_direction),
                        time_horizon=normalize_pdf_text(item.time_horizon),
                    )
                    for item in section.executive_items
                ),
            )
            for section in document.sections
        ),
    )


def _to_pdf_section(section: SectionDraft, *, max_evidences: int) -> PdfSection:
    return PdfSection(
        category=normalize_pdf_text(section.category),
        title=normalize_pdf_text(section.title),
        body=normalize_pdf_text((section.content or "").strip() or K_NO_INFORMATION),
        confidence_label=normalize_pdf_text(_confidence_label(section.confidence_score)),
        evidences=tuple(
            PdfEvidenceLine(
                document_version_id=normalize_pdf_text(item.document_version_id),
                quoted_text=normalize_pdf_text(item.quoted_text.strip()),
                relevance_score=item.relevance_score,
            )
            for item in section.evidences[:max_evidences]
        ),
    )


def _confidence_label(score: Optional[float]) -> str:
    if score is None:
        return K_NO_INFORMATION
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _register_report_fonts() -> None:
    if REPORT_FONT_REGULAR not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(REPORT_FONT_REGULAR, str(_require_font_file(NANUM_REGULAR_FONT_PATH))))
    if REPORT_FONT_BOLD not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(REPORT_FONT_BOLD, str(_require_font_file(NANUM_BOLD_FONT_PATH))))
    pdfmetrics.registerFontFamily(REPORT_FONT_FAMILY, normal=REPORT_FONT_REGULAR, bold=REPORT_FONT_BOLD)


def _require_font_file(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"Required Korean TTF font not found: {path}")
    return path


def _resolve_page_size(layout: PdfLayout) -> tuple[float, float]:
    base = A4 if layout.page_size.upper() == "A4" else A4
    return landscape(base) if layout.orientation.lower() == "landscape" else portrait(base)


def _build_styles(layout: PdfLayout) -> StyleSheet1:
    styles = getSampleStyleSheet()
    base_leading = 14
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], fontName=REPORT_FONT_BOLD, fontSize=layout.title_font_size, leading=27, textColor=NAVY, spaceAfter=4, alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="ReportSubtitle", parent=styles["BodyText"], fontName=REPORT_FONT_BOLD, fontSize=10.5, leading=14, textColor=ACCENT, spaceAfter=8, alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="SectionTitle", parent=styles["Heading2"], fontName=REPORT_FONT_BOLD, fontSize=16, leading=21, textColor=NAVY, spaceBefore=4, spaceAfter=10, keepWithNext=1))
    styles.add(ParagraphStyle(name="IssueTitle", parent=styles["Heading2"], fontName=REPORT_FONT_BOLD, fontSize=14, leading=19, textColor=NAVY, spaceBefore=0, spaceAfter=7, keepWithNext=1))
    styles.add(ParagraphStyle(name="Subheading", parent=styles["Heading4"], fontName=REPORT_FONT_BOLD, fontSize=11.2, leading=15, textColor=NAVY, spaceBefore=12, spaceAfter=6, keepWithNext=1))
    styles.add(ParagraphStyle(name="Body", parent=styles["BodyText"], fontName=REPORT_FONT_REGULAR, fontSize=10, leading=base_leading, textColor=DARK_TEXT, spaceBefore=0, spaceAfter=8, alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="ReportBullet", parent=styles["Body"], fontName=REPORT_FONT_REGULAR, fontSize=9.8, leading=13.8, leftIndent=12, firstLineIndent=0, bulletIndent=2, spaceAfter=4))
    styles.add(ParagraphStyle(name="BodyMuted", parent=styles["BodyText"], fontName=REPORT_FONT_REGULAR, fontSize=9, leading=12.5, textColor=SLATE, spaceAfter=5))
    styles.add(ParagraphStyle(name="MetaLabel", parent=styles["BodyText"], fontName=REPORT_FONT_BOLD, fontSize=8.8, leading=12, textColor=SLATE))
    styles.add(ParagraphStyle(name="MetaValue", parent=styles["BodyText"], fontName=REPORT_FONT_REGULAR, fontSize=8.8, leading=12, textColor=NAVY))
    styles.add(ParagraphStyle(name="EvidenceBody", parent=styles["BodyText"], fontName=REPORT_FONT_REGULAR, fontSize=8.8, leading=12.2, textColor=DARK_TEXT))
    styles.add(ParagraphStyle(name="BoxTitle", parent=styles["Heading4"], fontName=REPORT_FONT_BOLD, fontSize=10.5, leading=14, textColor=NAVY, spaceAfter=4, keepWithNext=1))
    styles.add(ParagraphStyle(name="ExecutiveNumber", parent=styles["BodyText"], fontName=REPORT_FONT_BOLD, fontSize=15, leading=18, textColor=ACCENT))
    styles.add(ParagraphStyle(name="ExecutiveTitle", parent=styles["BodyText"], fontName=REPORT_FONT_BOLD, fontSize=11.2, leading=15, textColor=NAVY, spaceAfter=4))
    styles.add(ParagraphStyle(name="ExecutiveSummary", parent=styles["BodyText"], fontName=REPORT_FONT_REGULAR, fontSize=9.8, leading=13.6, textColor=DARK_TEXT, spaceAfter=5))
    styles.add(ParagraphStyle(name="CategoryCardTitle", parent=styles["BoxTitle"], fontSize=10.8, leading=14.5, textColor=NAVY))
    styles.add(ParagraphStyle(name="CategoryCardBody", parent=styles["Body"], fontSize=9.1, leading=12.5, spaceAfter=3))
    styles.add(ParagraphStyle(name="ImplicationLabel", parent=styles["Subheading"], fontSize=10.8, leading=14.5, textColor=ACCENT, spaceBefore=14, spaceAfter=7, keepWithNext=1))
    return styles


def _build_story(document: PdfReportDocument, styles: StyleSheet1) -> list[object]:
    story: list[object] = [
        Paragraph(_xml_text(document.title), styles["ReportTitle"]),
        Paragraph(K_DAILY_BRIEF_EN, styles["ReportSubtitle"]),
        _build_compact_metadata(document, styles),
        Spacer(1, 6 * mm),
    ]
    if not document.sections:
        story.append(Paragraph(_xml_text(K_NO_INFORMATION), styles["BodyMuted"]))
        return story

    for index, section in enumerate(document.sections, start=1):
        if section.section_type in {"issues_heading", "categories", "implications", "sources"}:
            story.append(PageBreak())
        story.extend(_build_section_flowables(index, section, styles))
    has_sources_section = any(section.section_type == "sources" for section in document.sections)
    final_evidence = tuple(
        item for section in document.sections if section.section_type != "sources" for item in section.evidences
    )
    if final_evidence and not has_sources_section:
        story.extend(_build_final_evidence_flowables(final_evidence, styles))
    return story


def _build_compact_metadata(document: PdfReportDocument, styles: StyleSheet1) -> Table:
    meta = " | ".join(
        part for part in (
            f"\uae30\uc900\uc77c {_format_report_date(document.subtitle)}",
            f"\uc0dd\uc131 {_format_datetime(document.generated_at)}",
            _format_version(document.version),
        ) if part
    )
    table = Table([[Paragraph(_xml_text(meta), styles["MetaValue"])]], colWidths=[170 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.4, LIGHT_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return table


def _build_metadata_table(document: PdfReportDocument, styles: StyleSheet1) -> Table:
    rows = [
        [Paragraph(_xml_text("\uae30\uc900\uc77c"), styles["MetaLabel"]), Paragraph(_xml_text(_format_report_date(document.subtitle)), styles["MetaValue"])],
        [Paragraph(_xml_text("\uc0dd\uc131 \uc2dc\uac01"), styles["MetaLabel"]), Paragraph(_xml_text(_format_datetime(document.generated_at)), styles["MetaValue"])],
        [Paragraph(_xml_text("\ubc84\uc804"), styles["MetaLabel"]), Paragraph(_xml_text(_format_version(document.version)), styles["MetaValue"])],
    ]
    table = Table(rows, colWidths=[28 * mm, 142 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), REPORT_FONT_REGULAR),
        ("FONTNAME", (0, 0), (0, -1), REPORT_FONT_BOLD),
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LIGHT_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return table


def _build_section_flowables(index: int, section: PdfSection, styles: StyleSheet1) -> list[object]:
    if section.section_type == "executive":
        return _build_executive_flowables(section, styles)
    if section.section_type == "issue":
        return _build_issue_flowables(section, styles)
    if section.section_type == "categories":
        return _build_category_flowables(section, styles)
    if section.section_type == "implications":
        return _build_implication_flowables(section, styles)
    if section.section_type == "sources":
        return _build_source_flowables(section, styles)

    flowables: list[object] = [Paragraph(_xml_text(section.title), styles["SectionTitle"])]
    if section.section_type == "issues_heading":
        return flowables + [Spacer(1, 1 * mm)]
    flowables.extend(_body_flowables(section.body, styles, keep_subheadings=True))
    flowables.append(Spacer(1, 5 * mm))
    return flowables


def _build_executive_flowables(section: PdfSection, styles: StyleSheet1) -> list[object]:
    flowables: list[object] = [Paragraph(_xml_text(section.title), styles["SectionTitle"])]
    if section.executive_items:
        for index, item in enumerate(section.executive_items[:5], start=1):
            flowables.append(_build_executive_card(index, item, styles))
            flowables.append(Spacer(1, 2.8 * mm))
        return flowables

    lines = _split_paragraphs(section.body)[:5] or [K_NO_INFORMATION]
    for index, line in enumerate(lines, start=1):
        item = PdfExecutiveSummaryLine(title="", summary=line)
        flowables.append(_build_executive_card(index, item, styles))
        flowables.append(Spacer(1, 2.8 * mm))
    return flowables


def _build_executive_card(index: int, item: PdfExecutiveSummaryLine, styles: StyleSheet1) -> Table:
    title = _truncate_text(_display_text(item.title, default=""), 72)
    summary = _truncate_text(_display_text(item.summary), 165)
    content: list[object] = []
    if title:
        content.append(Paragraph(_xml_text(title), styles["ExecutiveTitle"]))
    content.append(Paragraph(_xml_text(summary), styles["ExecutiveSummary"]))
    metadata = _format_summary_metadata(item)
    if metadata:
        content.append(Paragraph(_xml_text(metadata), styles["BodyMuted"]))
    table = Table(
        [[Paragraph(f"{index:02d}", styles["ExecutiveNumber"]), content]],
        colWidths=[15 * mm, 151 * mm],
        hAlign="LEFT",
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("LINEBEFORE", (0, 0), (0, -1), 1.2, ACCENT),
        ("BOX", (0, 0), (-1, -1), 0.4, LIGHT_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def _build_issue_flowables(section: PdfSection, styles: StyleSheet1) -> list[object]:
    header = [
        Paragraph(_xml_text(section.title), styles["IssueTitle"]),
        Paragraph(_xml_text(_format_issue_metadata(section)), styles["BodyMuted"]),
        HRFlowable(width="100%", thickness=0.6, color=LIGHT_BORDER, spaceBefore=3, spaceAfter=7),
    ]
    flowables: list[object] = [CondPageBreak(54 * mm), KeepTogether(header)]
    for piece in _issue_body_flowables(section.body, styles):
        if _block_is_short(piece):
            flowables.append(KeepTogether(piece))
        else:
            flowables.extend(piece)
    flowables.append(Spacer(1, 8 * mm))
    return flowables


def _issue_body_flowables(body: str, styles: StyleSheet1) -> list[list[object]]:
    groups: list[list[str]] = []
    current: list[str] = []
    headings = {K_FACTS, K_MEANING, K_IMPACT, K_WATCH}
    for line in _split_paragraphs(body):
        if line in headings:
            if current:
                groups.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        groups.append(current)
    if not groups:
        return [[Paragraph(_xml_text("-"), styles["Body"])] ]

    result: list[list[object]] = []
    for group in groups:
        if group[0] in headings:
            items: list[object] = [Paragraph(_xml_text(group[0]), styles["Subheading"])]
            content = group[1:] or ["-"]
        else:
            items = []
            content = group
        items.extend(_paragraph_for_line(item, styles) for item in content)
        result.append(items)
    return result


def _body_flowables(body: str, styles: StyleSheet1, *, keep_subheadings: bool) -> list[object]:
    lines = _split_paragraphs(body)
    result: list[object] = []
    subheadings = {K_FACTS, K_MEANING, K_IMPACT, K_WATCH, K_OPPORTUNITY, K_RISK, K_MONITORING}
    for line in lines:
        style = styles["Subheading"] if line in subheadings else styles["Body"]
        result.append(_paragraph_for_line(line, styles, style=style))
    return result or [Paragraph(_xml_text("-"), styles["BodyMuted"])]


def _build_category_flowables(section: PdfSection, styles: StyleSheet1) -> list[object]:
    categories = ("\uc81c\ud488\u00b7\uae30\uc220", "\uacbd\uc7c1\uc0ac", "\uace0\uac1d\u00b7\uc218\uc694\uc0b0\uc5c5", "\uacf5\uae09\ub9dd\u00b7\uc0dd\uc0b0", "\uc815\ucc45\u00b7\uaddc\uc81c", "\uc2dc\uc7a5\u00b7\uacbd\uc601")
    grouped: dict[str, list[str]] = {category: [] for category in categories}
    current: str | None = None
    for line in _split_paragraphs(section.body):
        if line in grouped:
            current = line
        elif current:
            grouped[current].append(line)

    flowables: list[object] = [Paragraph(_xml_text(section.title), styles["SectionTitle"])]
    rows: list[list[object]] = []
    for row_index in range(0, len(categories), 2):
        row: list[object] = []
        for category in categories[row_index:row_index + 2]:
            content = grouped[category] or [f"- {K_NO_TRENDS}"]
            card: list[object] = [Paragraph(_xml_text(category), styles["CategoryCardTitle"])]
            for item in content[:2]:
                card.append(_paragraph_for_line(_truncate_text(item, 150), styles, style=styles["CategoryCardBody"]))
            row.append(card)
        rows.append(row)
    table = Table(rows, colWidths=[82 * mm, 82 * mm], hAlign="LEFT", splitByRow=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.5, LIGHT_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LIGHT_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    flowables.append(table)
    return flowables


def _build_implication_flowables(section: PdfSection, styles: StyleSheet1) -> list[object]:
    flowables: list[object] = [Paragraph(_xml_text(section.title), styles["SectionTitle"])]
    grouped = _split_implication_groups(section.body)
    labels = (
        (K_OPPORTUNITY, "OPPORTUNITY"),
        (K_RISK, "RISK"),
        (K_MONITORING, K_NEXT_WATCH_EN),
    )
    for source_label, display_label in labels:
        values = grouped.get(source_label, []) or ["-"]
        flowables.append(CondPageBreak(34 * mm))
        flowables.append(Paragraph(_xml_text(display_label), styles["ImplicationLabel"]))
        for value in values:
            flowables.append(_paragraph_for_line(value, styles))
        flowables.append(Spacer(1, 3 * mm))
    return flowables


def _split_implication_groups(body: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {K_OPPORTUNITY: [], K_RISK: [], K_MONITORING: []}
    current: str | None = None
    for line in _split_paragraphs(body):
        if line in groups:
            current = line
        elif current:
            groups[current].append(line)
    return groups


def _build_conclusion(groups: dict[str, list[str]]) -> str:
    for label in (K_OPPORTUNITY, K_RISK, K_MONITORING):
        if groups[label]:
            return f"\uacb0\ub860: {groups[label][0].lstrip('- ').strip()}"
    return f"\uacb0\ub860: {K_NO_INFORMATION}"


def _build_final_evidence_flowables(evidences: tuple[PdfEvidenceLine, ...], styles: StyleSheet1) -> list[object]:
    return [
        PageBreak(),
        Paragraph(_xml_text(K_ALL_SOURCES), styles["SectionTitle"]),
        _build_evidence_table(evidences, styles),
    ]


def _build_source_flowables(section: PdfSection, styles: StyleSheet1) -> list[object]:
    flowables: list[object] = [Paragraph(_xml_text(section.title), styles["SectionTitle"])]
    if not section.source_rows:
        return flowables + [Paragraph(_xml_text("-"), styles["BodyMuted"])]

    grouped: dict[str, list[PdfSourceLine]] = {}
    for source in section.source_rows:
        grouped.setdefault(_source_group_label(source), []).append(source)

    for group_index, (label, sources) in enumerate(grouped.items()):
        if group_index:
            flowables.append(Spacer(1, 4 * mm))
        flowables.append(Paragraph(_xml_text(label), styles["Subheading"]))
        flowables.append(_build_source_table(sources, styles))
    return flowables


def _build_source_table(sources: list[PdfSourceLine], styles: StyleSheet1) -> Table:
    header = ["\ubc88\ud638", K_SOURCES, "\uc81c\ubaa9", "\ubc1c\ud589\uc77c", "\ub9c1\ud06c"]
    rows: list[list[object]] = [[Paragraph(_xml_text(item), styles["MetaLabel"]) for item in header]]
    for index, source in enumerate(sources, start=1):
        rows.append([
            Paragraph(str(index), styles["EvidenceBody"]),
            Paragraph(_xml_text(_truncate_text(_source_display_name(source), 34)), styles["EvidenceBody"]),
            Paragraph(_xml_text(_truncate_text(_display_text(source.title), 220)), styles["EvidenceBody"]),
            Paragraph(_xml_text(_display_text(source.published_at)), styles["EvidenceBody"]),
            _build_source_link(source.url, styles),
        ])
    table = Table(rows, colWidths=[9 * mm, 34 * mm, 87 * mm, 24 * mm, 16 * mm], repeatRows=1, hAlign="LEFT", splitByRow=1)
    table.setStyle(_table_style())
    return table


def _build_source_link(url: str | None, styles: StyleSheet1) -> Paragraph:
    if not url:
        return Paragraph(_xml_text("-"), styles["EvidenceBody"])
    escaped_url = escape(url, quote=True)
    label = "\ub9c1\ud06c"
    return Paragraph(f'<link href="{escaped_url}"><font color="#2563EB">{label}</font></link>', styles["EvidenceBody"])


def _build_evidence_table(evidences: tuple[PdfEvidenceLine, ...], styles: StyleSheet1) -> Table:
    rows = [[Paragraph(_xml_text(K_SOURCES), styles["MetaLabel"]), Paragraph(_xml_text("\uadfc\uac70"), styles["MetaLabel"])]]
    for item in evidences:
        rows.append([
            Paragraph(_xml_text(item.document_version_id or K_NO_INFORMATION), styles["EvidenceBody"]),
            Paragraph(_xml_text(_format_evidence_line(item)), styles["EvidenceBody"]),
        ])
    table = Table(rows, colWidths=[36 * mm, 134 * mm], repeatRows=1, hAlign="LEFT", splitByRow=1)
    table.setStyle(_table_style())
    return table


def _table_style() -> TableStyle:
    return TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), REPORT_FONT_REGULAR),
        ("FONTNAME", (0, 0), (-1, 0), REPORT_FONT_BOLD),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2F7")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER), ("INNERGRID", (0, 0), (-1, -1), 0.5, LIGHT_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])


def _format_issue_metadata(section: PdfSection) -> str:
    parts = []
    if not _is_placeholder(section.category):
        parts.append(f"[{section.category}]")
    parts.append(_format_scored_label("\uc911\uc694\ub3c4", section.importance_score))
    reliability = _format_scored_label("\uc2e0\ub8b0\ub3c4", section.reliability_score)
    if reliability:
        parts.append(reliability)
    if not _is_placeholder(section.impact_direction):
        parts.append(section.impact_direction)
    if not _is_placeholder(section.time_horizon):
        parts.append(section.time_horizon)
    return "   ".join(part for part in parts if part)


def _format_scored_label(label: str, score: int | None) -> str:
    if score is None:
        return ""
    if score >= 85:
        grade = "\ub192\uc74c"
    elif score >= 70:
        grade = "\ubcf4\ud1b5"
    else:
        grade = "\uc8fc\uc758"
    return f"{label} {grade} {score}\uc810"


def _format_evidence_line(evidence: PdfEvidenceLine) -> str:
    base = evidence.quoted_text or K_NO_INFORMATION
    if evidence.relevance_score is None:
        return base
    return f"{base} (\uad00\ub828\ub3c4: {evidence.relevance_score:.2f})"


def _draw_page_header(page_canvas, pdf_doc, document: PdfReportDocument, layout: PdfLayout) -> None:
    page_canvas.saveState()
    page_width, page_height = pdf_doc.pagesize
    left = pdf_doc.leftMargin
    right = page_width - pdf_doc.rightMargin
    baseline = page_height - 10.5 * mm
    page_canvas.setFont(REPORT_FONT_REGULAR, 8.8)
    page_canvas.setFillColor(SLATE)
    page_canvas.drawString(left, baseline, normalize_pdf_text(_format_report_date(document.subtitle)))
    logo_height = 8 * mm
    logo_width = _draw_brand_logo(page_canvas, right, baseline - 1.5 * mm, logo_height)
    mywiki_x = right - logo_width - 14 * mm
    page_canvas.setFont(REPORT_FONT_BOLD, 10.5)
    page_canvas.setFillColor(NAVY)
    page_canvas.drawRightString(mywiki_x, baseline, "MyWiki")
    line_y = page_height - 18.5 * mm
    page_canvas.setStrokeColor(LIGHT_BORDER)
    page_canvas.setLineWidth(0.5)
    page_canvas.line(left, line_y, right, line_y)
    page_canvas.restoreState()


def _draw_brand_logo(page_canvas, right_x: float, bottom_y: float, target_height: float) -> float:
    if not BRAND_LOGO_PATH.exists():
        return 0.0
    try:
        image = ImageReader(str(BRAND_LOGO_PATH))
        width, height = image.getSize()
        if not width or not height:
            return 0.0
        target_width = target_height * width / height
        page_canvas.drawImage(image, right_x - target_width, bottom_y, width=target_width, height=target_height, preserveAspectRatio=True, mask="auto")
        return target_width
    except Exception as exc:  # pragma: no cover - artifact rendering should still succeed without a logo
        logger.warning("Unable to draw report logo: %s", exc)
        return 0.0


class _NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, document: PdfReportDocument, layout: PdfLayout, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []
        self._document = document
        self._layout = layout

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        page_count = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(page_count)
            super().showPage()
        super().save()

    def _draw_footer(self, page_count: int) -> None:
        page_width, _ = self._pagesize
        left = self._layout.margin_mm * mm
        right = page_width - self._layout.margin_mm * mm
        line_y = 15 * mm
        text_y = 9.8 * mm
        self.saveState()
        self.setStrokeColor(LIGHT_BORDER)
        self.setLineWidth(0.5)
        self.line(left, line_y, right, line_y)
        self.setFont(REPORT_FONT_REGULAR, 8)
        self.setFillColor(SLATE)
        self.drawString(left, text_y, "SK hynix Industry Trend Curation")
        self.drawRightString(right, text_y, f"{self._pageNumber} / {page_count}")
        self.restoreState()




def _paragraph_for_line(line: str, styles: StyleSheet1, *, style: ParagraphStyle | None = None) -> Paragraph:
    normalized = _display_text(line)
    bullet_match = re.match(r"^[-\u2022]\s*(.*)$", normalized)
    if bullet_match:
        bullet_text = _display_text(bullet_match.group(1))
        return Paragraph(_xml_text(bullet_text), styles["ReportBullet"], bulletText="\u2022")
    return Paragraph(_xml_text(normalized), style or styles["Body"])


def _block_is_short(flowables: list[object]) -> bool:
    paragraph_count = sum(isinstance(item, Paragraph) for item in flowables)
    text_length = sum(len(getattr(item, "text", "")) for item in flowables if isinstance(item, Paragraph))
    return paragraph_count <= 4 and text_length <= 900


def _is_placeholder(value: str | None) -> bool:
    normalized = normalize_pdf_text(value or "").strip()
    return normalized in {"", "-", K_NO_INFORMATION, f"- {K_NO_INFORMATION}", "N/A", "n/a", "None", "null"}


def _display_text(value: str | None, *, default: str = "-") -> str:
    normalized = normalize_pdf_text(value or "").strip()
    if _is_placeholder(normalized):
        return default
    return normalized


def _truncate_text(value: str, max_chars: int) -> str:
    normalized = _display_text(value, default="")
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "..."


def _format_summary_metadata(item: PdfExecutiveSummaryLine) -> str:
    parts: list[str] = []
    if not _is_placeholder(item.category):
        parts.append(f"[{item.category}]")
    importance = _format_scored_label("\uc911\uc694\ub3c4", item.importance_score)
    if importance:
        parts.append(importance)
    if not _is_placeholder(item.impact_direction):
        parts.append(item.impact_direction)
    if not _is_placeholder(item.time_horizon):
        parts.append(item.time_horizon)
    return "   ".join(parts)


def _source_group_label(source: PdfSourceLine) -> str:
    source_type = _display_text(source.source_type, default="")
    upper = source_type.upper()
    if "WIKI" in upper or "\ub0b4\ubd80" in source_type:
        return "MYWIKI"
    if "\ub274\uc2a4" in source_type or "NEWS" in upper:
        return "NEWS"
    return source_type or K_SOURCES


def _source_display_name(source: PdfSourceLine) -> str:
    if not _is_placeholder(source.source_name):
        return source.source_name
    source_type = _display_text(source.source_type)
    if "|" in source_type:
        return _display_text(source_type.split("|", 1)[1])
    return source_type


def _format_report_date(value: str) -> str:
    match = re.search(r"(\d{4})[-.](\d{2})[-.](\d{2})", value or "")
    if match:
        return f"{match.group(1)}.{match.group(2)}.{match.group(3)}"
    return value or K_NO_INFORMATION


def _format_datetime(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%Y.%m.%d %H:%M")
    except (TypeError, ValueError):
        return value or K_NO_INFORMATION


def _format_version(version: int | None) -> str:
    return f"v{version}.0" if version is not None else K_NO_INFORMATION


def _split_paragraphs(text: str) -> list[str]:
    return [normalize_pdf_text(segment.strip()) for segment in text.split("\n") if segment.strip()]


def _xml_text(value: str) -> str:
    return escape(normalize_pdf_text(value)).replace("\n", "<br/>")


def _log_document_preview(document: PdfReportDocument) -> None:
    logger.info("render_daily_report_pdf title=%r sections=%s renderer=%s", document.title, len(document.sections), REPORT_RENDERER_VERSION)
