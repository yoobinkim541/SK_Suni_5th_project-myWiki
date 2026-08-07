from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE
from pptx.enum.text import PP_ALIGN, MSO_VERTICAL_ANCHOR
from pptx.util import Inches, Pt

from .models import ReportCitationDraft, ReportSectionDraft, ReportSectionStatus
from .pdf_renderer import normalize_pdf_text


DEFAULT_PPT_TITLE = "\uc77c\uc77c \uc0b0\uc5c5 \ub3d9\ud5a5 \ubcf4\uace0\uc11c"
DEFAULT_PPT_FONT_NAME = "Malgun Gothic"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PPT_LOGO_PATH = PROJECT_ROOT / "assets" / "mySUNI.png"
PPT_LOGO_ENV = "MYWIKI_PPT_LOGO_PATH"
BRAND_NAVY = RGBColor(27, 43, 65)
BRAND_ORANGE = RGBColor(242, 101, 34)
BRAND_GOLD = RGBColor(247, 181, 0)
BRAND_SAND = RGBColor(247, 243, 236)
BRAND_MIST = RGBColor(239, 244, 247)
BRAND_TEXT = RGBColor(52, 61, 72)
BRAND_MUTED = RGBColor(104, 117, 132)


@dataclass(frozen=True)
class PptLayout:
    title_font_size: int = 28
    slide_title_font_size: int = 22
    body_font_size: int = 14
    meta_font_size: int = 11
    max_evidences_per_section: int = 6
    max_evidences_per_slide: int = 3
    max_agenda_items_per_slide: int = 5
    slide_width_inches: float = 13.333
    slide_height_inches: float = 7.5


@dataclass(frozen=True)
class PptEvidenceLine:
    document_version_id: str
    citation_order: int
    evidence_text: str
    relevance_score: Optional[float] = None


@dataclass(frozen=True)
class PptSection:
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
    evidences: tuple[PptEvidenceLine, ...] = ()


@dataclass(frozen=True)
class PptReportDocument:
    title: str
    subtitle: str
    generated_at: str
    report_date: str
    version: int
    layout: PptLayout = field(default_factory=PptLayout)
    sections: tuple[PptSection, ...] = ()


DEFAULT_DAILY_REPORT_PPT_LAYOUT = PptLayout()


def build_daily_report_ppt_document(
    *,
    report_key: str,
    version: int,
    sections: list[ReportSectionDraft],
    generated_at: Optional[str] = None,
    report_date: date | str | None = None,
    title: Optional[str] = None,
    layout: PptLayout = DEFAULT_DAILY_REPORT_PPT_LAYOUT,
) -> PptReportDocument:
    completed_sections = [
        _to_ppt_section(section, max_evidences=layout.max_evidences_per_section)
        for section in sections
        if section.status == ReportSectionStatus.COMPLETED
    ]
    normalized_generated_at = normalize_pdf_text(generated_at or _utc_now_iso())
    normalized_report_date = normalize_pdf_text(
        _resolve_report_date_text(report_date=report_date, generated_at=normalized_generated_at)
    )
    return PptReportDocument(
        title=normalize_pdf_text(title or DEFAULT_PPT_TITLE),
        subtitle=normalize_pdf_text(report_key),
        generated_at=normalized_generated_at,
        report_date=normalized_report_date,
        version=version,
        layout=layout,
        sections=tuple(completed_sections),
    )


def build_daily_report_ppt_filename(*, report_key: str, version: int) -> str:
    normalized_key = normalize_pdf_text(report_key).strip().replace(" ", "-")
    return f"{normalized_key}-v{version}.pptx"


def render_daily_report_ppt(document: PptReportDocument) -> bytes:
    normalized_document = _normalize_document(document)
    presentation = Presentation()
    presentation.slide_width = Inches(normalized_document.layout.slide_width_inches)
    presentation.slide_height = Inches(normalized_document.layout.slide_height_inches)

    _add_cover_slide(presentation, normalized_document)
    _add_agenda_slides(presentation, normalized_document)

    if not normalized_document.sections:
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        _fill_background(slide, BRAND_MIST)
        _add_slide_title(slide, "\uc644\ub8cc\ub41c \uc139\uc158", normalized_document.layout)
        _add_text_block(
            slide,
            left=0.9,
            top=1.8,
            width=6.5,
            height=1.2,
            text="\uc644\ub8cc\ub41c \uc139\uc158\uc774 \uc5c6\uc2b5\ub2c8\ub2e4.",
            font_size=20,
            layout=normalized_document.layout,
            color=BRAND_TEXT,
        )
    else:
        for index, section in enumerate(normalized_document.sections, start=1):
            _add_section_overview_slide(presentation, normalized_document, index, section)
            _add_section_highlight_slide(presentation, normalized_document, index, section)
        all_source_items = _collect_source_items(normalized_document.sections)
        if all_source_items:
            for chunk_index, source_chunk in enumerate(_chunked_text(all_source_items, 5), start=1):
                _add_sources_slide(presentation, normalized_document, chunk_index, source_chunk)

    buffer = BytesIO()
    presentation.save(buffer)
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


def _normalize_document(document: PptReportDocument) -> PptReportDocument:
    return PptReportDocument(
        title=normalize_pdf_text(document.title),
        subtitle=normalize_pdf_text(document.subtitle),
        generated_at=normalize_pdf_text(document.generated_at),
        report_date=normalize_pdf_text(document.report_date),
        version=document.version,
        layout=document.layout,
        sections=tuple(
            PptSection(
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
                    PptEvidenceLine(
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


def _to_ppt_section(section: ReportSectionDraft, *, max_evidences: int) -> PptSection:
    return PptSection(
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
        evidences=tuple(_to_ppt_evidence(citation) for citation in section.news_citations[:max_evidences]),
    )


def _to_ppt_evidence(citation: ReportCitationDraft) -> PptEvidenceLine:
    return PptEvidenceLine(
        document_version_id=citation.document_version_id,
        citation_order=citation.citation_order,
        evidence_text=(citation.evidence_text or "").strip() or "Citation reference",
        relevance_score=citation.relevance_score,
    )


def _add_cover_slide(presentation: Presentation, document: PptReportDocument) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    _fill_background(slide, BRAND_NAVY)
    _add_accent_band(slide, 0.0, 0.0, 0.45, 7.5, BRAND_ORANGE)
    _add_accent_band(slide, 0.45, 0.0, 0.16, 7.5, BRAND_GOLD)
    _add_accent_band(slide, 9.7, 5.8, 2.8, 0.22, BRAND_ORANGE)
    _add_accent_band(slide, 9.95, 6.2, 2.3, 0.12, BRAND_GOLD)
    _add_logo(slide, left=9.7, top=0.7, height=0.7)

    _add_text_block(
        slide,
        left=1.0,
        top=0.85,
        width=3.4,
        height=0.5,
        text="Mywiki",
        font_size=19,
        bold=True,
        color=BRAND_GOLD,
        layout=document.layout,
    )
    _add_text_block(
        slide,
        left=1.0,
        top=1.6,
        width=6.8,
        height=1.25,
        text=document.title,
        font_size=document.layout.title_font_size + 2,
        bold=True,
        color=RGBColor(255, 255, 255),
        layout=document.layout,
    )
    _add_text_block(
        slide,
        left=1.0,
        top=2.95,
        width=7.2,
        height=0.85,
        text=document.subtitle,
        font_size=17,
        color=RGBColor(212, 221, 230),
        layout=document.layout,
    )
    _add_text_block(
        slide,
        left=1.0,
        top=3.85,
        width=6.1,
        height=0.7,
        text="AI 산업 변화를 섹션별 흐름으로 정리한 데일리 브리핑",
        font_size=18,
        color=RGBColor(255, 255, 255),
        layout=document.layout,
    )

    _add_info_card(
        slide,
        left=1.0,
        top=5.2,
        width=2.3,
        height=1.2,
        title="Report Date",
        body=_format_header_date_korean(document.report_date),
        fill=RGBColor(255, 255, 255),
        title_color=BRAND_MUTED,
        body_color=BRAND_NAVY,
    )
    _add_info_card(
        slide,
        left=3.55,
        top=5.2,
        width=1.8,
        height=1.2,
        title="Version",
        body=f"v{document.version}",
        fill=RGBColor(255, 247, 234),
        title_color=BRAND_MUTED,
        body_color=BRAND_ORANGE,
    )
    _add_info_card(
        slide,
        left=5.65,
        top=5.2,
        width=2.2,
        height=1.2,
        title="Format",
        body="PPTX",
        fill=RGBColor(248, 241, 221),
        title_color=BRAND_MUTED,
        body_color=BRAND_NAVY,
    )
    _add_text_block(
        slide,
        left=9.55,
        top=6.5,
        width=2.4,
        height=0.3,
        text="mySUNI inspired deck",
        font_size=10,
        color=RGBColor(214, 222, 230),
        layout=document.layout,
        align=PP_ALIGN.RIGHT,
    )


def _add_agenda_slides(presentation: Presentation, document: PptReportDocument) -> None:
    if not document.sections:
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        _fill_background(slide, BRAND_MIST)
        _add_slide_title(slide, "Agenda", document.layout)
        _add_text_block(
            slide,
            left=1.1,
            top=1.8,
            width=5.0,
            height=1.0,
            text="\uc644\ub8cc\ub41c \uc139\uc158\uc774 \uc5c6\uc2b5\ub2c8\ub2e4.",
            font_size=18,
            layout=document.layout,
            color=BRAND_TEXT,
        )
        return

    agenda_lines = [f"{index}. {section.title}" for index, section in enumerate(document.sections, start=1)]
    for chunk_index, items in enumerate(_chunked_text(agenda_lines, document.layout.max_agenda_items_per_slide), start=1):
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        _fill_background(slide, RGBColor(255, 252, 247))
        _add_accent_band(slide, 0.0, 0.0, 0.28, 7.5, BRAND_ORANGE)
        _add_logo(slide, left=10.6, top=0.55, height=0.42)
        title = "Agenda" if chunk_index == 1 else f"Agenda {chunk_index}"
        _add_slide_title(slide, title, document.layout)
        _add_bullet_card(slide, left=0.95, top=1.45, width=5.35, height=4.95, title="Sections", items=items)
        _add_bullet_card(
            slide,
            left=6.75,
            top=1.45,
            width=5.05,
            height=4.95,
            title="\ubcf4\uae30 \ud750\ub984",
            items=[
                "섹션 요약 슬라이드로 이슈를 파악합니다.",
                "Highlights \uc2ac\ub77c\uc774\ub4dc\uc5d0\uc11c \ud575\uc2ec \uc0ac\uc2e4\uacfc \uc2dc\uc0ac\uc810\uc744 \ubd05\ub2c8\ub2e4.",
                "\ub9c8\uc9c0\ub9c9 \ucd9c\ucc98 \ubaa9\ub85d\uc5d0\uc11c \uadfc\uac70\ub97c \ud55c\ubc88\uc5d0 \ud655\uc778\ud569\ub2c8\ub2e4.",
            ],
        )


def _add_section_overview_slide(
    presentation: Presentation,
    document: PptReportDocument,
    index: int,
    section: PptSection,
) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    _fill_background(slide, RGBColor(255, 255, 255))
    _add_accent_band(slide, 0.0, 0.0, 0.18, 7.5, BRAND_GOLD)
    _add_logo(slide, left=10.7, top=0.58, height=0.38)
    _add_slide_title(slide, f"{index}. {section.title}", document.layout)
    _add_meta_chips(slide, section, document.layout)
    _add_summary_panel(slide, section.current_summary or "No summary available.", document.layout)
    _add_bullet_card(
        slide,
        left=8.35,
        top=1.95,
        width=3.8,
        height=4.5,
        title="\ud575\uc2ec \uc2e0\ud638",
        items=[
            f"\uc911\uc694\ub3c4: {section.importance_score}" if section.importance_score is not None else "\uc911\uc694\ub3c4: n/a",
            f"\uc601\ud5a5: {section.impact_direction}" if section.impact_direction else "\uc601\ud5a5: n/a",
            f"\uc2dc\uac04 \ubc94\uc704: {section.time_horizon}" if section.time_horizon else "\uc2dc\uac04 \ubc94\uc704: n/a",
            f"\ucd9c\ucc98 \uac1c\uc218: {len(section.evidences)}",
        ],
    )


def _add_section_highlight_slide(
    presentation: Presentation,
    document: PptReportDocument,
    index: int,
    section: PptSection,
) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    _fill_background(slide, BRAND_MIST)
    _add_slide_title(
        slide,
        f"{index}. {section.title} | Highlights",
        document.layout,
        title_height=1.05,
        divider_top=1.45,
    )

    columns = [
        ("\ud575\uc2ec \uc0ac\uc2e4", list(section.key_facts[:3])),
        ("SK\ud558\uc774\ub2c9\uc2a4 \uc601\ud5a5", list(section.implications[:3])),
        ("\ub2e4\uc74c \ud655\uc778 \uc0ac\ud56d", list(section.watch_points[:3]) or list(section.historical_context[:3])),
    ]
    positions = [(0.9, 1.7), (4.45, 1.7), (8.0, 1.7)]
    for (title, items), (left, top) in zip(columns, positions):
        _add_bullet_card(slide, left=left, top=top, width=3.0, height=4.6, title=title, items=items or ["\ud45c\uc2dc\ud560 \ud56d\ubaa9\uc774 \uc5c6\uc2b5\ub2c8\ub2e4."])


def _add_sources_slide(
    presentation: Presentation,
    document: PptReportDocument,
    chunk_index: int,
    source_chunk: list[str],
) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    _fill_background(slide, RGBColor(255, 255, 255))
    title = "\uc804\uccb4 \ucd9c\ucc98 \ubaa9\ub85d" if chunk_index == 1 else f"\uc804\uccb4 \ucd9c\ucc98 \ubaa9\ub85d {chunk_index}"
    _add_slide_title(slide, title, document.layout)
    _add_bullet_card(slide, left=0.9, top=1.45, width=11.25, height=5.05, title="\ucd9c\ucc98", items=source_chunk)



def _collect_source_items(sections: tuple[PptSection, ...]) -> list[str]:
    items: list[str] = []
    for section in sections:
        for evidence in section.evidences:
            items.append(_format_source_line(section.title, evidence, len(items) + 1))
    return items



def _format_source_line(section_title: str, evidence: PptEvidenceLine, source_index: int) -> str:
    base = evidence.evidence_text or "\ucd9c\ucc98 \uc815\ubcf4 \uc5c6\uc74c"
    suffix = ""
    if evidence.relevance_score is not None:
        suffix = f" (\uad00\ub828\ub3c4: {evidence.relevance_score:.2f})"
    return f"{source_index}. [{section_title}] {evidence.document_version_id} - {base}{suffix}"


def _resolve_logo_path() -> Path | None:
    env_value = os.environ.get(PPT_LOGO_ENV)
    if env_value:
        candidate = Path(env_value)
        if candidate.exists():
            return candidate
    if DEFAULT_PPT_LOGO_PATH.exists():
        return DEFAULT_PPT_LOGO_PATH
    return None


def _add_logo(slide, *, left: float, top: float, height: float) -> None:
    logo_path = _resolve_logo_path()
    if logo_path is None:
        return
    slide.shapes.add_picture(str(logo_path), Inches(left), Inches(top), height=Inches(height))


def _add_accent_band(slide, left: float, top: float, width: float, height: float, color: RGBColor) -> None:
    shape = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()


def _add_info_card(slide, *, left: float, top: float, width: float, height: float, title: str, body: str, fill: RGBColor | None = None, title_color: RGBColor | None = None, body_color: RGBColor | None = None) -> None:
    shape = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill or RGBColor(255, 255, 255)
    shape.line.color.rgb = RGBColor(227, 219, 207)
    frame = shape.text_frame
    frame.clear()
    frame.vertical_anchor = MSO_VERTICAL_ANCHOR.MIDDLE
    p1 = frame.paragraphs[0]
    p1.alignment = PP_ALIGN.LEFT
    r1 = p1.add_run()
    r1.text = title
    r1.font.name = DEFAULT_PPT_FONT_NAME
    r1.font.size = Pt(10)
    r1.font.bold = True
    r1.font.color.rgb = title_color or BRAND_MUTED
    p2 = frame.add_paragraph()
    r2 = p2.add_run()
    r2.text = body
    r2.font.name = DEFAULT_PPT_FONT_NAME
    r2.font.size = Pt(16)
    r2.font.bold = True
    r2.font.color.rgb = body_color or BRAND_NAVY


def _add_meta_chips(slide, section: PptSection, layout: PptLayout) -> None:
    items = [f"\uce74\ud14c\uace0\ub9ac  {section.category}", f"\uc0c1\ud0dc  {section.status}"]
    if section.importance_score is not None:
        items.append(f"\uc911\uc694\ub3c4  {section.importance_score}")
    if section.impact_direction:
        items.append(f"\uc601\ud5a5  {section.impact_direction}")
    if section.time_horizon:
        items.append(f"\uc2dc\uac04  {section.time_horizon}")
    left = 0.9
    top = 1.25
    for item in items:
        width = max(1.3, min(2.6, 0.12 * len(item) + 0.6))
        shape = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(0.42))
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor(245, 247, 250)
        shape.line.color.rgb = RGBColor(221, 227, 233)
        frame = shape.text_frame
        frame.clear()
        p = frame.paragraphs[0]
        r = p.add_run()
        r.text = item
        r.font.name = DEFAULT_PPT_FONT_NAME
        r.font.size = Pt(layout.meta_font_size)
        r.font.color.rgb = BRAND_MUTED
        left += width + 0.15


def _add_summary_panel(slide, summary_text: str, layout: PptLayout) -> None:
    panel = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE, Inches(0.9), Inches(1.95), Inches(7.0), Inches(4.5))
    panel.fill.solid()
    panel.fill.fore_color.rgb = RGBColor(255, 255, 255)
    panel.line.color.rgb = RGBColor(225, 231, 236)
    frame = panel.text_frame
    frame.clear()
    frame.word_wrap = True
    p1 = frame.paragraphs[0]
    r1 = p1.add_run()
    r1.text = "\ud604\uc7ac \uc694\uc57d"
    r1.font.name = DEFAULT_PPT_FONT_NAME
    r1.font.size = Pt(15)
    r1.font.bold = True
    r1.font.color.rgb = BRAND_ORANGE
    p2 = frame.add_paragraph()
    r2 = p2.add_run()
    r2.text = summary_text
    r2.font.name = DEFAULT_PPT_FONT_NAME
    r2.font.size = Pt(layout.body_font_size)
    r2.font.color.rgb = BRAND_TEXT


def _add_bullet_card(slide, *, left: float, top: float, width: float, height: float, title: str, items: list[str]) -> None:
    shape = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(255, 255, 255)
    shape.line.color.rgb = RGBColor(225, 231, 236)
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    p1 = frame.paragraphs[0]
    r1 = p1.add_run()
    r1.text = title
    r1.font.name = DEFAULT_PPT_FONT_NAME
    r1.font.size = Pt(15)
    r1.font.bold = True
    r1.font.color.rgb = BRAND_NAVY
    for item in items:
        p = frame.add_paragraph()
        p.text = item
        p.bullet = True
        p.level = 0
        p.font.name = DEFAULT_PPT_FONT_NAME
        p.font.size = Pt(13)
        p.font.color.rgb = BRAND_TEXT


def _fill_background(slide, color: RGBColor) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def _add_slide_title(
    slide,
    text: str,
    layout: PptLayout,
    *,
    title_height: float = 0.6,
    divider_top: float = 1.0,
) -> None:
    _add_text_block(
        slide,
        left=0.7,
        top=0.35,
        width=11.9,
        height=title_height,
        text=text,
        font_size=layout.slide_title_font_size,
        bold=True,
        color=BRAND_NAVY,
        layout=layout,
    )
    line = slide.shapes.add_shape(
        MSO_AUTO_SHAPE_TYPE.RECTANGLE,
        Inches(0.7),
        Inches(divider_top),
        Inches(11.7),
        Inches(0.03),
    )
    line.fill.solid()
    line.fill.fore_color.rgb = BRAND_ORANGE
    line.line.fill.background()


def _add_text_block(
    slide,
    *,
    left: float,
    top: float,
    width: float,
    height: float,
    text: str,
    font_size: int | float,
    layout: PptLayout,
    bold: bool = False,
    color: RGBColor | None = None,
    align: PP_ALIGN = PP_ALIGN.LEFT,
    word_wrap: bool = True,
) -> None:
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = word_wrap
    paragraph = frame.paragraphs[0]
    paragraph.alignment = align
    run = paragraph.add_run()
    run.text = text
    font = run.font
    font.name = DEFAULT_PPT_FONT_NAME
    font.size = Pt(font_size)
    font.bold = bold
    if color is not None:
        font.color.rgb = color


def _add_bullet_block(
    slide,
    *,
    left: float,
    top: float,
    width: float,
    height: float,
    items: list[str],
    font_size: int | float,
    layout: PptLayout,
    color: RGBColor | None = None,
) -> None:
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    for index, item in enumerate(items):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = item
        paragraph.level = 0
        paragraph.bullet = True
        paragraph.font.name = DEFAULT_PPT_FONT_NAME
        paragraph.font.size = Pt(font_size)
        paragraph.font.color.rgb = color or BRAND_TEXT


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


def _chunked(values: tuple[PptEvidenceLine, ...], chunk_size: int) -> list[tuple[PptEvidenceLine, ...]]:
    return [values[index : index + chunk_size] for index in range(0, len(values), chunk_size)]


def _chunked_text(values: list[str], chunk_size: int) -> list[list[str]]:
    return [values[index : index + chunk_size] for index in range(0, len(values), chunk_size)]


def _format_evidence_line(evidence: PptEvidenceLine) -> str:
    base = evidence.evidence_text or "\ucd9c\ucc98 \uc815\ubcf4 \uc5c6\uc74c"
    if evidence.relevance_score is None:
        return f"[{evidence.document_version_id}] {base}"
    return f"[{evidence.document_version_id}] {base} (\uad00\ub828\ub3c4: {evidence.relevance_score:.2f})"
