from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import escape
from io import BytesIO
from pathlib import Path
import logging
import unicodedata
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.styles import ParagraphStyle, StyleSheet1, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..analysis.interface import SectionDraft


logger = logging.getLogger(__name__)

REPORT_RENDERER_VERSION = "REPORTLAB-TTF-V3"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_FONT_DIR = PROJECT_ROOT / "assets" / "fonts"
NANUM_REGULAR_FONT_PATH = PROJECT_FONT_DIR / "NanumGothic-Regular.ttf"
NANUM_BOLD_FONT_PATH = PROJECT_FONT_DIR / "NanumGothic-Bold.ttf"
REPORT_LOGO_PATH = PROJECT_ROOT / "assets" / "mySUNI.png"
REPORT_FONT_FAMILY = "MyWikiReportFont"
REPORT_FONT_REGULAR = f"{REPORT_FONT_FAMILY}-Regular"
REPORT_FONT_BOLD = f"{REPORT_FONT_FAMILY}-Bold"
HEADER_BRAND_TEXT = "Mywiki"
KST = timezone(timedelta(hours=9), name="Asia/Seoul")
UNSUPPORTED_TEXT_REPLACEMENTS = {
    "✓": "[check]",
    "✔": "[check]",
    "☑": "[checked]",
    "✅": "[check]",
}


@dataclass(frozen=True)
class PdfLayout:
    page_size: str = "A4"
    orientation: str = "portrait"
    margin_mm: int = 16
    title_font_size: int = 20
    heading_font_size: int = 13
    body_font_size: int = 10
    line_height: float = 1.6
    max_evidences_per_section: int = 3


@dataclass(frozen=True)
class PdfEvidenceLine:
    document_version_id: str
    quoted_text: str
    relevance_score: Optional[float] = None


@dataclass(frozen=True)
class PdfSection:
    category: str
    title: str
    body: str
    confidence_label: str
    evidences: tuple[PdfEvidenceLine, ...] = ()


@dataclass(frozen=True)
class PdfReportDocument:
    title: str
    subtitle: str
    generated_at: str
    version: int
    layout: PdfLayout = field(default_factory=PdfLayout)
    sections: tuple[PdfSection, ...] = ()


DEFAULT_DAILY_REPORT_LAYOUT = PdfLayout()


def normalize_pdf_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value or "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    sanitized: list[str] = []
    for char in normalized:
        replacement = UNSUPPORTED_TEXT_REPLACEMENTS.get(char)
        if replacement is not None:
            sanitized.append(replacement)
            continue
        codepoint = ord(char)
        if 0x1F300 <= codepoint <= 0x1FAFF:
            sanitized.append("[emoji]")
            continue
        if unicodedata.category(char) == "Cs":
            sanitized.append("?")
            continue
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

    buffer = BytesIO()
    layout = normalized_document.layout
    doc = SimpleDocTemplate(
        buffer,
        pagesize=_resolve_page_size(layout),
        leftMargin=layout.margin_mm * mm,
        rightMargin=layout.margin_mm * mm,
        topMargin=(layout.margin_mm + 18) * mm,
        bottomMargin=(layout.margin_mm + 12) * mm,
        title=normalized_document.title,
        author="myWiki",
    )
    styles = _build_styles(layout)
    story = _build_story(normalized_document, styles)
    doc.build(
        story,
        onFirstPage=lambda canvas, pdf_doc: _draw_header_footer(canvas, pdf_doc, normalized_document, layout),
        onLaterPages=lambda canvas, pdf_doc: _draw_header_footer(canvas, pdf_doc, normalized_document, layout),
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
                        document_version_id=normalize_pdf_text(evidence.document_version_id),
                        quoted_text=normalize_pdf_text(evidence.quoted_text),
                        relevance_score=evidence.relevance_score,
                    )
                    for evidence in section.evidences
                ),
            )
            for section in document.sections
        ),
    )



def _to_pdf_section(section: SectionDraft, *, max_evidences: int) -> PdfSection:
    body = normalize_pdf_text((section.content or "").strip() or "No content")
    evidences = tuple(
        PdfEvidenceLine(
            document_version_id=normalize_pdf_text(evidence.document_version_id),
            quoted_text=normalize_pdf_text(evidence.quoted_text.strip()),
            relevance_score=evidence.relevance_score,
        )
        for evidence in section.evidences[:max_evidences]
    )
    return PdfSection(
        category=normalize_pdf_text(section.category),
        title=normalize_pdf_text(section.title),
        body=body,
        confidence_label=normalize_pdf_text(_confidence_label(section.confidence_score)),
        evidences=evidences,
    )



def _confidence_label(score: Optional[float]) -> str:
    if score is None:
        return "pending"
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"



def _utc_now_iso() -> str:
    return datetime.now(KST).replace(microsecond=0).isoformat()



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
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            fontName=REPORT_FONT_BOLD,
            fontSize=layout.title_font_size,
            leading=layout.title_font_size * 1.35,
            textColor=colors.HexColor("#0F172A"),
            spaceAfter=10,
            alignment=TA_LEFT,
            wordWrap="CJK",
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionTitle",
            parent=styles["Heading2"],
            fontName=REPORT_FONT_BOLD,
            fontSize=layout.heading_font_size,
            leading=layout.heading_font_size * 1.35,
            textColor=colors.HexColor("#0F172A"),
            spaceBefore=10,
            spaceAfter=6,
            wordWrap="CJK",
        )
    )
    styles.add(
        ParagraphStyle(
            name="Body",
            parent=styles["BodyText"],
            fontName=REPORT_FONT_REGULAR,
            fontSize=layout.body_font_size,
            leading=layout.body_font_size * layout.line_height,
            textColor=colors.HexColor("#111827"),
            spaceAfter=6,
            alignment=TA_LEFT,
            wordWrap="CJK",
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyMuted",
            parent=styles["BodyText"],
            fontName=REPORT_FONT_REGULAR,
            fontSize=layout.body_font_size,
            leading=layout.body_font_size * layout.line_height,
            textColor=colors.HexColor("#475569"),
            spaceAfter=4,
            wordWrap="CJK",
        )
    )
    styles.add(
        ParagraphStyle(
            name="EvidenceHeading",
            parent=styles["Heading4"],
            fontName=REPORT_FONT_BOLD,
            fontSize=layout.body_font_size,
            leading=layout.body_font_size * 1.45,
            textColor=colors.HexColor("#111827"),
            spaceBefore=8,
            spaceAfter=4,
            wordWrap="CJK",
        )
    )
    styles.add(
        ParagraphStyle(
            name="EvidenceBody",
            parent=styles["BodyText"],
            fontName=REPORT_FONT_REGULAR,
            fontSize=max(layout.body_font_size - 0.5, 8.5),
            leading=max(layout.body_font_size - 0.5, 8.5) * 1.55,
            textColor=colors.HexColor("#111827"),
            wordWrap="CJK",
        )
    )
    styles.add(
        ParagraphStyle(
            name="MetaLabel",
            parent=styles["BodyText"],
            fontName=REPORT_FONT_BOLD,
            fontSize=layout.body_font_size,
            leading=layout.body_font_size * 1.45,
            textColor=colors.HexColor("#334155"),
            wordWrap="CJK",
        )
    )
    styles.add(
        ParagraphStyle(
            name="MetaValue",
            parent=styles["BodyText"],
            fontName=REPORT_FONT_REGULAR,
            fontSize=layout.body_font_size,
            leading=layout.body_font_size * 1.45,
            textColor=colors.HexColor("#111827"),
            wordWrap="CJK",
        )
    )
    return styles



def _build_story(document: PdfReportDocument, styles: StyleSheet1) -> list[object]:
    story: list[object] = [
        Paragraph(_xml_text(document.title), styles["ReportTitle"]),
        Spacer(1, 3 * mm),
        _build_metadata_table(document, styles),
        Spacer(1, 6 * mm),
    ]
    if not document.sections:
        story.append(Paragraph("No completed sections available.", styles["BodyMuted"]))
        return story

    for index, section in enumerate(document.sections, start=1):
        story.extend(_build_section_flowables(index, section, styles))
    return story



def _build_metadata_table(document: PdfReportDocument, styles: StyleSheet1) -> Table:
    rows = [
        [Paragraph("Report key", styles["MetaLabel"]), Paragraph(_xml_text(document.subtitle), styles["MetaValue"])],
        [Paragraph("Version", styles["MetaLabel"]), Paragraph(str(document.version), styles["MetaValue"])],
        [Paragraph("Generated at", styles["MetaLabel"]), Paragraph(_xml_text(document.generated_at), styles["MetaValue"])],
        [Paragraph("Renderer", styles["MetaLabel"]), Paragraph(REPORT_RENDERER_VERSION, styles["MetaValue"])],
    ]
    table = Table(rows, colWidths=[30 * mm, 140 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), REPORT_FONT_REGULAR),
                ("FONTNAME", (0, 0), (0, -1), REPORT_FONT_BOLD),
                ("FONTSIZE", (0, 0), (-1, -1), document.layout.body_font_size),
                ("LEADING", (0, 0), (-1, -1), document.layout.body_font_size * 1.45),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#475569")),
                ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#111827")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table



def _build_section_flowables(index: int, section: PdfSection, styles: StyleSheet1) -> list[object]:
    flowables: list[object] = [
        Paragraph(_xml_text(f"{index}. {section.title}"), styles["SectionTitle"]),
        Paragraph(_xml_text(f"Category: {section.category} | Confidence: {section.confidence_label}"), styles["BodyMuted"]),
    ]
    for paragraph in _split_paragraphs(section.body):
        flowables.append(Paragraph(_xml_text(paragraph), styles["Body"]))
    if section.evidences:
        flowables.append(Paragraph("Evidence", styles["EvidenceHeading"]))
        flowables.append(_build_evidence_table(section.evidences, styles))
    flowables.append(Spacer(1, 4 * mm))
    return flowables



def _build_evidence_table(evidences: tuple[PdfEvidenceLine, ...], styles: StyleSheet1) -> Table:
    rows = [[Paragraph("Document", styles["MetaLabel"]), Paragraph("Evidence", styles["MetaLabel"])]]
    for evidence in evidences:
        rows.append([
            Paragraph(_xml_text(evidence.document_version_id), styles["MetaValue"]),
            Paragraph(_xml_text(_format_evidence_line(evidence)), styles["EvidenceBody"]),
        ])
    table = Table(rows, colWidths=[34 * mm, 136 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), REPORT_FONT_REGULAR),
                ("FONTNAME", (0, 0), (-1, 0), REPORT_FONT_BOLD),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table



def _draw_header_footer(canvas, pdf_doc, document: PdfReportDocument, layout: PdfLayout) -> None:
    canvas.saveState()
    _draw_header(canvas, pdf_doc, document, layout)
    _draw_footer(canvas, pdf_doc, document, layout)
    canvas.restoreState()



def _draw_header(canvas, pdf_doc, document: PdfReportDocument, layout: PdfLayout) -> None:
    page_top_y = pdf_doc.height + pdf_doc.topMargin
    header_center_y = page_top_y + 7 * mm
    header_rule_y = page_top_y + 1.5 * mm
    left_x = pdf_doc.leftMargin
    right_x = pdf_doc.pagesize[0] - pdf_doc.rightMargin
    brand_text = normalize_pdf_text(HEADER_BRAND_TEXT)
    date_text = _header_date_text(document)

    canvas.setFont(REPORT_FONT_REGULAR, max(layout.body_font_size, 9))
    canvas.setFillColor(colors.HexColor("#334155"))
    canvas.drawRightString(right_x, header_center_y - 1, date_text)

    brand_x = left_x
    logo = _load_logo_reader()
    if logo is not None:
        logo_width, logo_height = _scaled_logo_size(logo, max_height=11 * mm, max_width=24 * mm)
        logo_y = header_center_y - (logo_height / 2)
        canvas.drawImage(
            logo,
            left_x,
            logo_y,
            width=logo_width,
            height=logo_height,
            preserveAspectRatio=True,
            mask="auto",
        )
        brand_x = left_x + logo_width + (3 * mm)

    canvas.setFont(REPORT_FONT_BOLD, max(layout.body_font_size + 1.5, 11))
    canvas.setFillColor(colors.HexColor("#0F172A"))
    canvas.drawString(brand_x, header_center_y - 1, brand_text)

    canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
    canvas.setLineWidth(0.5)
    canvas.line(
        pdf_doc.leftMargin,
        header_rule_y,
        pdf_doc.pagesize[0] - pdf_doc.rightMargin,
        header_rule_y,
    )



def _draw_footer(canvas, pdf_doc, document: PdfReportDocument, layout: PdfLayout) -> None:
    canvas.setFont(REPORT_FONT_REGULAR, max(layout.body_font_size - 1, 8))
    canvas.setFillColor(colors.HexColor("#475569"))
    footer_y = pdf_doc.bottomMargin - 6 * mm
    footer_text = normalize_pdf_text(f"Generated at {document.generated_at} | {REPORT_RENDERER_VERSION}")
    canvas.drawString(pdf_doc.leftMargin, footer_y, footer_text)
    canvas.drawRightString(pdf_doc.pagesize[0] - pdf_doc.rightMargin, footer_y, normalize_pdf_text(f"Page {canvas.getPageNumber()}"))



def _load_logo_reader() -> ImageReader | None:
    if not REPORT_LOGO_PATH.exists():
        return None
    try:
        return ImageReader(str(REPORT_LOGO_PATH))
    except Exception:
        logger.exception("failed_to_load_report_logo", extra={"path": str(REPORT_LOGO_PATH)})
        return None



def _scaled_logo_size(logo: ImageReader, *, max_height: float, max_width: float) -> tuple[float, float]:
    width_px, height_px = logo.getSize()
    if not width_px or not height_px:
        return max_width, max_height
    scale = min(max_width / width_px, max_height / height_px)
    return width_px * scale, height_px * scale



def _header_date_text(document: PdfReportDocument) -> str:
    raw = (document.generated_at or "").strip()
    if not raw:
        return normalize_pdf_text(_utc_now_iso().split("T", 1)[0])
    for candidate in (raw, raw.replace("Z", "+00:00")):
        try:
            return normalize_pdf_text(datetime.fromisoformat(candidate).date().isoformat())
        except ValueError:
            continue
    return normalize_pdf_text(raw.split("T", 1)[0])


def _split_paragraphs(text: str) -> list[str]:
    paragraphs = [normalize_pdf_text(segment.strip()) for segment in text.split("\n")]
    return [paragraph for paragraph in paragraphs if paragraph] or [""]



def _format_evidence_line(evidence: PdfEvidenceLine) -> str:
    base = normalize_pdf_text(evidence.quoted_text)
    if evidence.relevance_score is None:
        return base
    return normalize_pdf_text(f"{base} (relevance: {evidence.relevance_score:.2f})")



def _xml_text(value: str) -> str:
    return escape(normalize_pdf_text(value)).replace("\n", "<br/>")



def _log_document_preview(document: PdfReportDocument) -> None:
    logger.info(
        "render_daily_report_pdf called title=%r subtitle=%r generated_at=%r renderer=%s",
        document.title,
        document.subtitle,
        document.generated_at,
        REPORT_RENDERER_VERSION,
    )
    for index, section in enumerate(document.sections, start=1):
        logger.info(
            "render_daily_report_pdf section[%s] title=%r body_repr=%r evidences_repr=%r",
            index,
            section.title,
            section.body,
            [evidence.quoted_text for evidence in section.evidences],
        )
