from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

from docx import Document as DocxDocumentFactory
from docx.enum.section import WD_SECTION_START
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from .models import ReportCitationDraft, ReportSectionDraft, ReportSectionStatus
from .pdf_renderer import normalize_pdf_text


DEFAULT_WORD_FONT_NAME = "Malgun Gothic"
DEFAULT_WORD_TITLE = "\uc77c\uc77c \uc0b0\uc5c5 \ub3d9\ud5a5 \ubcf4\uace0\uc11c"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORD_LOGO_PATH = PROJECT_ROOT / "assets" / "mySUNI.png"
WORD_LOGO_ENV = "MYWIKI_WORD_LOGO_PATH"


@dataclass(frozen=True)
class WordLayout:
    margin_mm: float = 16
    top_margin_mm: float = 28
    title_font_size: int = 21
    title_date_font_size: int = 11
    heading_font_size: int = 13
    body_font_size: int = 10
    metadata_label_width_mm: float = 32
    evidence_doc_width_mm: float = 38
    max_evidences_per_section: int = 6
    header_logo_height_mm: float = 9
    header_brand_font_size: float = 10.5
    header_date_font_size: int = 9


@dataclass(frozen=True)
class WordEvidenceLine:
    document_version_id: str
    citation_order: int
    evidence_text: str
    relevance_score: Optional[float] = None


@dataclass(frozen=True)
class WordSection:
    category: str
    title: str
    status: str
    importance_score: Optional[int]
    impact_direction: Optional[str]
    time_horizon: Optional[str]
    current_summary: Optional[str]
    key_facts: tuple[str, ...] = ()
    historical_context: tuple[str, ...] = ()
    implications: tuple[str, ...] = ()
    watch_points: tuple[str, ...] = ()
    evidences: tuple[WordEvidenceLine, ...] = ()


@dataclass(frozen=True)
class WordReportDocument:
    title: str
    subtitle: str
    generated_at: str
    report_date: str
    version: int
    layout: WordLayout = field(default_factory=WordLayout)
    sections: tuple[WordSection, ...] = ()


DEFAULT_DAILY_REPORT_WORD_LAYOUT = WordLayout()


def build_daily_report_word_document(
    *,
    report_key: str,
    version: int,
    sections: list[ReportSectionDraft],
    generated_at: Optional[str] = None,
    report_date: date | str | None = None,
    title: Optional[str] = None,
    layout: WordLayout = DEFAULT_DAILY_REPORT_WORD_LAYOUT,
) -> WordReportDocument:
    completed_sections = [
        _to_word_section(section, max_evidences=layout.max_evidences_per_section)
        for section in sections
        if section.status == ReportSectionStatus.COMPLETED
    ]
    normalized_generated_at = normalize_pdf_text(generated_at or _utc_now_iso())
    normalized_report_date = normalize_pdf_text(
        _resolve_report_date_text(report_date=report_date, generated_at=normalized_generated_at)
    )
    return WordReportDocument(
        title=normalize_pdf_text(title or DEFAULT_WORD_TITLE),
        subtitle=normalize_pdf_text(report_key),
        generated_at=normalized_generated_at,
        report_date=normalized_report_date,
        version=version,
        layout=layout,
        sections=tuple(completed_sections),
    )


def build_daily_report_word_filename(*, report_key: str, version: int) -> str:
    normalized_key = normalize_pdf_text(report_key).strip().replace(" ", "-")
    return f"{normalized_key}-v{version}.docx"


def render_daily_report_word(document: WordReportDocument) -> bytes:
    normalized_document = _normalize_document(document)
    doc = DocxDocumentFactory()
    _configure_page_layout(doc, normalized_document.layout)
    _configure_styles(doc, normalized_document.layout)
    _configure_header(doc, normalized_document)

    core_props = doc.core_properties
    core_props.title = DEFAULT_WORD_TITLE
    core_props.author = "myWiki"

    title_paragraph = doc.add_paragraph(style="MyWikiTitle")
    title_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_paragraph.add_run(DEFAULT_WORD_TITLE)

    date_paragraph = doc.add_paragraph(style="MyWikiTitleDate")
    date_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    date_paragraph.add_run(_format_header_date_korean(normalized_document.report_date))

    doc.add_paragraph("", style="MyWikiBody")

    if not normalized_document.sections:
        doc.add_paragraph("No completed sections available.", style="MyWikiBody")
    else:
        for index, section in enumerate(normalized_document.sections, start=1):
            if index > 1:
                doc.add_page_break()
            _render_section(doc, index, section)

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _resolve_report_date_text(*, report_date: date | str | None, generated_at: str) -> str:
    if isinstance(report_date, date):
        return report_date.isoformat()
    if isinstance(report_date, str) and report_date.strip():
        raw = report_date.strip()
        if "T" in raw:
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
            except ValueError:
                return raw.split("T", 1)[0]
        return raw
    try:
        return datetime.fromisoformat(generated_at.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return generated_at.split("T", 1)[0]


def _normalize_document(document: WordReportDocument) -> WordReportDocument:
    return WordReportDocument(
        title=normalize_pdf_text(document.title),
        subtitle=normalize_pdf_text(document.subtitle),
        generated_at=normalize_pdf_text(document.generated_at),
        report_date=normalize_pdf_text(document.report_date),
        version=document.version,
        layout=document.layout,
        sections=tuple(
            WordSection(
                category=normalize_pdf_text(section.category),
                title=normalize_pdf_text(section.title),
                status=normalize_pdf_text(section.status),
                importance_score=section.importance_score,
                impact_direction=normalize_pdf_text(section.impact_direction) if section.impact_direction else None,
                time_horizon=normalize_pdf_text(section.time_horizon) if section.time_horizon else None,
                current_summary=normalize_pdf_text(section.current_summary) if section.current_summary else None,
                key_facts=tuple(normalize_pdf_text(item) for item in section.key_facts),
                historical_context=tuple(normalize_pdf_text(item) for item in section.historical_context),
                implications=tuple(normalize_pdf_text(item) for item in section.implications),
                watch_points=tuple(normalize_pdf_text(item) for item in section.watch_points),
                evidences=tuple(
                    WordEvidenceLine(
                        document_version_id=normalize_pdf_text(evidence.document_version_id),
                        citation_order=evidence.citation_order,
                        evidence_text=normalize_pdf_text(evidence.evidence_text or ""),
                        relevance_score=evidence.relevance_score,
                    )
                    for evidence in section.evidences
                ),
            )
            for section in document.sections
        ),
    )


def _to_word_section(section: ReportSectionDraft, *, max_evidences: int) -> WordSection:
    return WordSection(
        category=section.category.value,
        title=section.title,
        status=section.status.value,
        importance_score=section.importance_score,
        impact_direction=section.impact_direction.value if section.impact_direction else None,
        time_horizon=section.time_horizon.value if section.time_horizon else None,
        current_summary=section.current_summary,
        key_facts=tuple(section.key_facts),
        historical_context=tuple(section.historical_context),
        implications=tuple(section.implications),
        watch_points=tuple(section.watch_points),
        evidences=tuple(_to_word_evidence(citation) for citation in section.news_citations[:max_evidences]),
    )


def _to_word_evidence(citation: ReportCitationDraft) -> WordEvidenceLine:
    return WordEvidenceLine(
        document_version_id=citation.document_version_id,
        citation_order=citation.citation_order,
        evidence_text=(citation.evidence_text or "").strip() or "Citation reference",
        relevance_score=citation.relevance_score,
    )


def _configure_page_layout(doc, layout: WordLayout) -> None:
    for section in doc.sections:
        section.top_margin = Mm(layout.top_margin_mm)
        section.bottom_margin = Mm(layout.margin_mm)
        section.left_margin = Mm(layout.margin_mm)
        section.right_margin = Mm(layout.margin_mm)
        section.header_distance = Mm(7)
        section.footer_distance = Mm(8)
        section.start_type = WD_SECTION_START.NEW_PAGE


def _configure_styles(doc, layout: WordLayout) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = DEFAULT_WORD_FONT_NAME
    normal.font.size = Pt(layout.body_font_size)

    if "MyWikiTitle" not in doc.styles:
        style = doc.styles.add_style("MyWikiTitle", WD_STYLE_TYPE.PARAGRAPH)
        style.font.name = DEFAULT_WORD_FONT_NAME
        style.font.bold = True
        style.font.size = Pt(layout.title_font_size)
        style.paragraph_format.space_after = Pt(4)

    if "MyWikiTitleDate" not in doc.styles:
        style = doc.styles.add_style("MyWikiTitleDate", WD_STYLE_TYPE.PARAGRAPH)
        style.font.name = DEFAULT_WORD_FONT_NAME
        style.font.size = Pt(layout.title_date_font_size)
        style.font.color.rgb = RGBColor(107, 114, 128)
        style.paragraph_format.space_after = Pt(14)

    if "MyWikiHeading" not in doc.styles:
        style = doc.styles.add_style("MyWikiHeading", WD_STYLE_TYPE.PARAGRAPH)
        style.font.name = DEFAULT_WORD_FONT_NAME
        style.font.bold = True
        style.font.size = Pt(layout.heading_font_size)
        style.paragraph_format.space_before = Pt(10)
        style.paragraph_format.space_after = Pt(4)

    if "MyWikiBody" not in doc.styles:
        style = doc.styles.add_style("MyWikiBody", WD_STYLE_TYPE.PARAGRAPH)
        style.font.name = DEFAULT_WORD_FONT_NAME
        style.font.size = Pt(layout.body_font_size)
        style.paragraph_format.space_after = Pt(3)

    if "MyWikiMuted" not in doc.styles:
        style = doc.styles.add_style("MyWikiMuted", WD_STYLE_TYPE.PARAGRAPH)
        style.font.name = DEFAULT_WORD_FONT_NAME
        style.font.size = Pt(max(layout.body_font_size - 1, 8))
        style.paragraph_format.space_after = Pt(3)


def _configure_header(doc, document: WordReportDocument) -> None:
    for section in doc.sections:
        header = section.header
        header.is_linked_to_previous = False

        table = header.add_table(
            rows=1,
            cols=2,
            width=section.page_width - section.left_margin - section.right_margin,
        )
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        _clear_table_borders(table)
        _set_row_bottom_border(table.rows[0], color="C7CDD4", size="6")

        left_cell, right_cell = table.rows[0].cells
        left_cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        right_cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

        left_para = left_cell.paragraphs[0]
        left_para.paragraph_format.space_after = Pt(0)
        left_para.paragraph_format.space_before = Pt(0)
        left_para.alignment = WD_ALIGN_PARAGRAPH.LEFT

        logo_path = _resolve_logo_path()
        if logo_path is not None:
            picture_run = left_para.add_run()
            picture_run.add_picture(str(logo_path), height=Mm(document.layout.header_logo_height_mm))
            left_para.add_run("  ")

        brand_run = left_para.add_run("Mywiki")
        _set_run_font(brand_run, size=document.layout.header_brand_font_size, bold=True)

        right_para = right_cell.paragraphs[0]
        right_para.paragraph_format.space_after = Pt(0)
        right_para.paragraph_format.space_before = Pt(0)
        right_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT

        date_run = right_para.add_run(_format_header_date_dots(document.report_date))
        _set_run_font(date_run, size=document.layout.header_date_font_size)


def _resolve_logo_path() -> Path | None:
    env_value = os.environ.get(WORD_LOGO_ENV)
    if env_value:
        candidate = Path(env_value)
        if candidate.exists():
            return candidate
    if DEFAULT_WORD_LOGO_PATH.exists():
        return DEFAULT_WORD_LOGO_PATH
    return None


def _clear_table_borders(table) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)

    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border = borders.find(qn(f"w:{edge}"))
        if border is None:
            border = OxmlElement(f"w:{edge}")
            borders.append(border)
        border.set(qn("w:val"), "nil")


def _set_row_bottom_border(row, *, color: str, size: str) -> None:
    for cell in row.cells:
        tc_pr = cell._tc.get_or_add_tcPr()
        borders = tc_pr.first_child_found_in("w:tcBorders")
        if borders is None:
            borders = OxmlElement("w:tcBorders")
            tc_pr.append(borders)
        bottom = borders.find(qn("w:bottom"))
        if bottom is None:
            bottom = OxmlElement("w:bottom")
            borders.append(bottom)
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), size)
        bottom.set(qn("w:space"), "0")
        bottom.set(qn("w:color"), color)


def _set_run_font(run, *, size: float, bold: bool = False) -> None:
    run.bold = bold
    run.font.name = DEFAULT_WORD_FONT_NAME
    run._element.rPr.rFonts.set(qn("w:ascii"), DEFAULT_WORD_FONT_NAME)
    run._element.rPr.rFonts.set(qn("w:hAnsi"), DEFAULT_WORD_FONT_NAME)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), DEFAULT_WORD_FONT_NAME)
    run.font.size = Pt(size)


def _format_header_date_dots(value: str) -> str:
    parsed = _parse_date_text(value)
    if parsed is None:
        return value
    return f"{parsed.year:04d}.{parsed.month:02d}.{parsed.day:02d}"


def _format_header_date_korean(value: str) -> str:
    parsed = _parse_date_text(value)
    if parsed is None:
        return value
    return f"{parsed.year}\ub144 {parsed.month}\uc6d4 {parsed.day}\uc77c"


def _parse_date_text(value: str) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    candidate = raw.split("T", 1)[0].replace(".", "-")
    try:
        return date.fromisoformat(candidate)
    except ValueError:
        return None


def _render_section(doc, index: int, section: WordSection) -> None:
    doc.add_paragraph(f"{index}. {section.title}", style="MyWikiHeading")
    meta_bits = [f"Category: {section.category}", f"Status: {section.status}"]
    if section.importance_score is not None:
        meta_bits.append(f"Importance: {section.importance_score}")
    if section.impact_direction:
        meta_bits.append(f"Impact: {section.impact_direction}")
    if section.time_horizon:
        meta_bits.append(f"Time horizon: {section.time_horizon}")
    doc.add_paragraph(" | ".join(meta_bits), style="MyWikiMuted")

    _add_labeled_paragraph(doc, "Current summary", section.current_summary)
    _add_bullet_block(doc, "Key facts", section.key_facts)
    _add_bullet_block(doc, "Historical context", section.historical_context)
    _add_bullet_block(doc, "Implications", section.implications)
    _add_bullet_block(doc, "Watch points", section.watch_points)

    if section.evidences:
        doc.add_paragraph("Evidence", style="MyWikiHeading")
        table = doc.add_table(rows=1, cols=2)
        table.style = "Table Grid"
        table.rows[0].cells[0].text = "Document"
        table.rows[0].cells[1].text = "Evidence"
        for evidence in section.evidences:
            row = table.add_row().cells
            row[0].text = evidence.document_version_id
            row[1].text = _format_evidence_line(evidence)

    doc.add_paragraph("", style="MyWikiBody")


def _add_labeled_paragraph(doc, label: str, value: Optional[str]) -> None:
    if not value:
        return
    paragraph = doc.add_paragraph(style="MyWikiBody")
    run = paragraph.add_run(f"{label}: ")
    run.bold = True
    paragraph.add_run(value)


def _add_bullet_block(doc, label: str, items: tuple[str, ...]) -> None:
    if not items:
        return
    heading = doc.add_paragraph(style="MyWikiBody")
    run = heading.add_run(f"{label}:")
    run.bold = True
    for item in items:
        doc.add_paragraph(item, style="List Bullet")


def _format_evidence_line(evidence: WordEvidenceLine) -> str:
    base = evidence.evidence_text or "Citation reference"
    if evidence.relevance_score is None:
        return base
    return f"{base} (relevance: {evidence.relevance_score:.2f})"
