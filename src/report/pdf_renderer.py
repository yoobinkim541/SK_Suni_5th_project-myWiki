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
class PdfSection:
    category: str
    title: str
    body: str
    confidence_label: str
    evidences: tuple[PdfEvidenceLine, ...] = ()
    section_type: str = "content"
    importance_score: int | None = None
    reliability_score: int | None = None
    source_rows: tuple[PdfSourceLine, ...] = ()


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
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], fontName=REPORT_FONT_BOLD, fontSize=layout.title_font_size, leading=layout.title_font_size * 1.25, textColor=NAVY, spaceAfter=10, alignment=TA_LEFT, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="SectionTitle", parent=styles["Heading2"], fontName=REPORT_FONT_BOLD, fontSize=layout.heading_font_size, leading=layout.heading_font_size * 1.35, textColor=NAVY, spaceBefore=2, spaceAfter=7, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="IssueTitle", parent=styles["Heading2"], fontName=REPORT_FONT_BOLD, fontSize=13, leading=18, textColor=NAVY, spaceAfter=5, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="Subheading", parent=styles["Heading4"], fontName=REPORT_FONT_BOLD, fontSize=10.5, leading=14.5, textColor=NAVY, spaceBefore=7, spaceAfter=3, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="Body", parent=styles["BodyText"], fontName=REPORT_FONT_REGULAR, fontSize=layout.body_font_size, leading=layout.body_font_size * layout.line_height, textColor=colors.HexColor("#111827"), spaceAfter=4, alignment=TA_LEFT, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="BodyMuted", parent=styles["BodyText"], fontName=REPORT_FONT_REGULAR, fontSize=9, leading=12.5, textColor=SLATE, spaceAfter=4, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="MetaLabel", parent=styles["BodyText"], fontName=REPORT_FONT_BOLD, fontSize=9.5, leading=13, textColor=SLATE, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="MetaValue", parent=styles["BodyText"], fontName=REPORT_FONT_REGULAR, fontSize=9.5, leading=13, textColor=NAVY, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="EvidenceBody", parent=styles["BodyText"], fontName=REPORT_FONT_REGULAR, fontSize=8.8, leading=12, textColor=colors.HexColor("#111827"), wordWrap="CJK"))
    styles.add(ParagraphStyle(name="BoxTitle", parent=styles["Heading4"], fontName=REPORT_FONT_BOLD, fontSize=10.5, leading=14, textColor=NAVY, wordWrap="CJK"))
    return styles


def _build_story(document: PdfReportDocument, styles: StyleSheet1) -> list[object]:
    story: list[object] = [
        Paragraph(_xml_text(document.title), styles["ReportTitle"]),
        _build_metadata_table(document, styles),
        Spacer(1, 5 * mm),
    ]
    if not document.sections:
        story.append(Paragraph(_xml_text(K_NO_INFORMATION), styles["BodyMuted"]))
        return story

    for index, section in enumerate(document.sections, start=1):
        if section.section_type in {"issues_heading", "categories", "implications", "sources"}:
            story.append(PageBreak())
        story.extend(_build_section_flowables(index, section, styles))
    final_evidence = tuple(
        item for section in document.sections if section.section_type != "sources" for item in section.evidences
    )
    if final_evidence:
        story.extend(_build_final_evidence_flowables(final_evidence, styles))
    return story


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
    flowables.append(Spacer(1, 4 * mm))
    return flowables


def _build_issue_flowables(section: PdfSection, styles: StyleSheet1) -> list[object]:
    title = Paragraph(_xml_text(section.title), styles["IssueTitle"])
    metadata = Paragraph(_xml_text(_format_issue_metadata(section)), styles["BodyMuted"])
    pieces = _issue_body_flowables(section.body, styles)
    opening = [title, metadata]
    if pieces:
        opening.extend(pieces.pop(0))
    flowables: list[object] = [KeepTogether(opening), Spacer(1, 1 * mm)]
    for piece in pieces:
        flowables.append(KeepTogether(piece))
    flowables.append(Spacer(1, 7 * mm))
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
        return [[Paragraph(_xml_text(K_NO_INFORMATION), styles["Body"])]]

    result: list[list[object]] = []
    for group in groups:
        if group[0] in headings:
            items: list[object] = [Paragraph(_xml_text(group[0]), styles["Subheading"])]
            content = group[1:] or [K_NO_INFORMATION]
        else:
            items = []
            content = group
        items.extend(Paragraph(_xml_text(item), styles["Body"]) for item in content)
        result.append(items)
    return result


def _body_flowables(body: str, styles: StyleSheet1, *, keep_subheadings: bool) -> list[object]:
    lines = _split_paragraphs(body)
    result: list[object] = []
    subheadings = {K_FACTS, K_MEANING, K_IMPACT, K_WATCH, K_OPPORTUNITY, K_RISK, K_MONITORING}
    for line in lines:
        style = styles["Subheading"] if line in subheadings else styles["Body"]
        item = Paragraph(_xml_text(line), style)
        result.append(item)
    return result or [Paragraph(_xml_text(K_NO_INFORMATION), styles["BodyMuted"])]


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
    for index, category in enumerate(categories):
        if index == 3:
            flowables.append(PageBreak())
        content = grouped[category] or [f"- {K_NO_TRENDS}"]
        block: list[object] = [Paragraph(_xml_text(category), styles["Subheading"])]
        block.extend(Paragraph(_xml_text(item), styles["Body"]) for item in content)
        flowables.extend([KeepTogether(block), Spacer(1, 2.5 * mm)])
    return flowables


def _build_implication_flowables(section: PdfSection, styles: StyleSheet1) -> list[object]:
    flowables: list[object] = [Paragraph(_xml_text(section.title), styles["SectionTitle"])]
    grouped = _split_implication_groups(section.body)
    for label in (K_OPPORTUNITY, K_RISK, K_MONITORING):
        values = grouped.get(label, []) or [K_NO_INFORMATION]
        flowables.append(Paragraph(_xml_text(label), styles["Subheading"]))
        flowables.extend(Paragraph(_xml_text(value), styles["Body"]) for value in values)
        flowables.append(Spacer(1, 2.5 * mm))
    conclusion = _build_conclusion(grouped)
    flowables.extend([Spacer(1, 2.5 * mm), Paragraph(_xml_text(conclusion), styles["Subheading"]), Spacer(1, 2 * mm)])
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
        return flowables + [Paragraph(_xml_text(K_NO_INFORMATION), styles["BodyMuted"])]
    header = ["\ubc88\ud638", K_SOURCES, "\uc81c\ubaa9", "\ubc1c\ud589\uc77c", "\ub9c1\ud06c"]
    rows: list[list[object]] = [[Paragraph(_xml_text(item), styles["MetaLabel"]) for item in header]]
    for index, source in enumerate(section.source_rows, start=1):
        link = "\uc6d0\ubb38 \ubcf4\uae30" if source.url else K_NO_INFORMATION
        rows.append([
            Paragraph(str(index), styles["EvidenceBody"]),
            Paragraph(_xml_text(source.source_type or K_NO_INFORMATION), styles["EvidenceBody"]),
            Paragraph(_xml_text(source.title or K_NO_INFORMATION), styles["EvidenceBody"]),
            Paragraph(_xml_text(source.published_at or K_NO_INFORMATION), styles["EvidenceBody"]),
            _build_source_link(source.url, styles),
        ])
    table = Table(rows, colWidths=[10 * mm, 32 * mm, 68 * mm, 29 * mm, 31 * mm], repeatRows=1, hAlign="LEFT", splitByRow=1)
    table.setStyle(_table_style())
    flowables.append(table)
    return flowables


def _build_source_link(url: str | None, styles: StyleSheet1) -> Paragraph:
    if not url:
        return Paragraph(_xml_text(K_NO_INFORMATION), styles["EvidenceBody"])
    escaped_url = escape(url, quote=True)
    label = "\uc6d0\ubb38 \ubcf4\uae30"
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
    category = section.category or K_NO_INFORMATION
    importance = _format_scored_label("\uc911\uc694\ub3c4", section.importance_score)
    reliability = _format_scored_label("\uc2e0\ub8b0\ub3c4", section.reliability_score)
    return f"[{category}]   {importance}   |   {reliability}"


def _format_scored_label(label: str, score: int | None) -> str:
    if score is None:
        return f"{label} {K_NO_INFORMATION}"
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
    page_canvas.setFont(REPORT_FONT_REGULAR, 9)
    page_canvas.setFillColor(SLATE)
    page_canvas.drawString(left, baseline, normalize_pdf_text(_format_report_date(document.subtitle)))
    logo_height = 8 * mm
    logo_width = _draw_brand_logo(page_canvas, right, baseline - 1.5 * mm, logo_height)
    mywiki_x = right - logo_width - 14 * mm
    page_canvas.setFont(REPORT_FONT_BOLD, 10.5)
    page_canvas.setFillColor(NAVY)
    page_canvas.drawRightString(mywiki_x, baseline, "MyWiki")
    line_y = page_height - 18 * mm
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
        line_y = 16 * mm
        text_y = 10.5 * mm
        self.saveState()
        self.setStrokeColor(LIGHT_BORDER)
        self.setLineWidth(0.5)
        self.line(left, line_y, right, line_y)
        self.setFont(REPORT_FONT_REGULAR, 8.5)
        self.setFillColor(SLATE)
        self.drawString(left, text_y, "SK hynix Industry Trend Curation")
        self.drawRightString(right, text_y, f"{self._pageNumber} / {page_count}")
        self.restoreState()


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
