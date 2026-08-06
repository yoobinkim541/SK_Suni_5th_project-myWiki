from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Iterable, Optional

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE
from pptx.enum.text import MSO_VERTICAL_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from .models import ReportCitationDraft, ReportSectionDraft, ReportSectionStatus, ReportWikiReferenceDraft
from .pdf_renderer import normalize_pdf_text

DEFAULT_PPT_TITLE = "\uc77c\uc77c \uc0b0\uc5c5 \ub3d9\ud5a5 \ubcf4\uace0\uc11c"
DEFAULT_PPT_FONT_NAME = "Malgun Gothic"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PPT_LOGO_PATH = PROJECT_ROOT / "assets" / "mySUNI.png"
PPT_LOGO_ENV = "MYWIKI_PPT_LOGO_PATH"

BRAND_NAVY = RGBColor(27, 43, 65)
BRAND_ORANGE = RGBColor(242, 101, 34)
BRAND_GOLD = RGBColor(247, 181, 0)
BRAND_MIST = RGBColor(244, 247, 249)
BRAND_LINE = RGBColor(216, 224, 230)
BRAND_TEXT = RGBColor(43, 55, 68)
BRAND_MUTED = RGBColor(103, 116, 129)
WHITE = RGBColor(255, 255, 255)
CATEGORY_ORDER = ("\uc81c\ud488\u00b7\uae30\uc220", "\uacbd\uc7c1\uc0ac", "\uace0\uac1d\u00b7\uc218\uc694\uc0b0\uc5c5", "\uacf5\uae09\ub9dd\u00b7\uc0dd\uc0b0", "\uc815\ucc45\u00b7\uaddc\uc81c", "\uc2dc\uc7a5\u00b7\uacbd\uc601")


@dataclass(frozen=True)
class PptLayout:
    title_font_size: int = 30
    slide_title_font_size: int = 26
    body_font_size: int = 15
    key_font_size: int = 18
    meta_font_size: int = 11
    source_font_size: int = 9
    max_evidences_per_section: int = 6
    max_summary_issues: int = 5
    max_overview_issues: int = 10
    max_detail_issues: int = 4
    slide_width_inches: float = 13.333
    slide_height_inches: float = 7.5


@dataclass(frozen=True)
class PptSource:
    key: str
    source_type: str
    title: str
    publisher: str | None = None
    published_at: str | None = None


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
    sources: tuple[PptSource, ...] = ()


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


def build_daily_report_ppt_document(*, report_key: str, version: int, sections: list[ReportSectionDraft], generated_at: Optional[str] = None, report_date: date | str | None = None, title: Optional[str] = None, layout: PptLayout = DEFAULT_DAILY_REPORT_PPT_LAYOUT) -> PptReportDocument:
    """Build a briefing view from the completed report sections used by Word and PDF."""
    completed = [_to_ppt_section(item, max_evidences=layout.max_evidences_per_section) for item in sections if item.status == ReportSectionStatus.COMPLETED]
    generated = normalize_pdf_text(generated_at or _utc_now_iso())
    report_day = normalize_pdf_text(_resolve_report_date_text(report_date=report_date, generated_at=generated))
    return PptReportDocument(
        title=normalize_pdf_text(title or DEFAULT_PPT_TITLE),
        subtitle="AI \ubc0f \ubc18\ub3c4\uccb4 \uc0b0\uc5c5\uc758 \uc8fc\uc694 \ubcc0\ud654\ub97c \uc774\uc288\ubcc4\ub85c \uc815\ub9ac\ud55c \ub370\uc77c\ub9ac \ube0c\ub9ac\ud551",
        generated_at=generated, report_date=report_day, version=version, layout=layout, sections=tuple(completed),
    )


def build_daily_report_ppt_filename(*, report_key: str, version: int) -> str:
    return f"{normalize_pdf_text(report_key).strip().replace(' ', '-')}-v{version}.pptx"


def render_daily_report_ppt(document: PptReportDocument) -> bytes:
    document = _normalize_document(document)
    presentation = Presentation()
    presentation.slide_width = Inches(document.layout.slide_width_inches)
    presentation.slide_height = Inches(document.layout.slide_height_inches)
    _add_cover_slide(presentation, document)
    sections = _ordered_sections(document.sections)
    if not sections:
        _add_no_data_slide(presentation, document)
    else:
        sources = _collect_sources(sections)
        details = sections[:document.layout.max_detail_issues]
        estimate = 1 + 2 + len(details) + 2 + 1 + max(1, (len(sources) + 7) // 8)
        if estimate >= 10:
            _add_agenda_slide(presentation, document)
        _add_today_summary_slide(presentation, document, sections)
        _add_issue_overview_slide(presentation, document, sections)
        for index, section in enumerate(details, 1):
            _add_issue_analysis_slides(presentation, document, index, section, _source_numbers(sources))
        _add_category_trend_slide(presentation, document, sections, CATEGORY_ORDER[:3])
        _add_category_trend_slide(presentation, document, sections, CATEGORY_ORDER[3:])
        _add_implications_slide(presentation, document, sections)
        _add_source_slides(presentation, document, sources)
    _add_common_chrome(presentation, document)
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
    def clean(text: str | None) -> str | None:
        return normalize_pdf_text(text) if text else None
    return PptReportDocument(
        title=normalize_pdf_text(document.title), subtitle=normalize_pdf_text(document.subtitle),
        generated_at=normalize_pdf_text(document.generated_at), report_date=normalize_pdf_text(document.report_date),
        version=document.version, layout=document.layout,
        sections=tuple(PptSection(
            category=normalize_pdf_text(section.category), title=normalize_pdf_text(section.title), status=normalize_pdf_text(section.status),
            importance_score=section.importance_score, impact_direction=clean(section.impact_direction), time_horizon=clean(section.time_horizon),
            current_summary=clean(section.current_summary), key_facts=tuple(normalize_pdf_text(x) for x in section.key_facts),
            historical_context=tuple(normalize_pdf_text(x) for x in section.historical_context), implications=tuple(normalize_pdf_text(x) for x in section.implications),
            watch_points=tuple(normalize_pdf_text(x) for x in section.watch_points),
            sources=tuple(PptSource(key=normalize_pdf_text(source.key), source_type=normalize_pdf_text(source.source_type), title=normalize_pdf_text(source.title), publisher=clean(source.publisher), published_at=clean(source.published_at)) for source in section.sources),
        ) for section in document.sections),
    )


def _to_ppt_section(section: ReportSectionDraft, *, max_evidences: int) -> PptSection:
    return PptSection(
        category=section.category.value, title=section.title, status=section.status.value, importance_score=section.importance_score,
        impact_direction=section.impact_direction.value if section.impact_direction else None,
        time_horizon=section.time_horizon.value if section.time_horizon else None, current_summary=section.current_summary,
        key_facts=tuple(section.key_facts), historical_context=tuple(section.historical_context), implications=tuple(section.implications), watch_points=tuple(section.watch_points),
        sources=tuple(_to_ppt_sources(section.news_citations[:max_evidences], section.wiki_references)),
    )


def _to_ppt_sources(citations: list[ReportCitationDraft], wiki_references: list[ReportWikiReferenceDraft]) -> Iterable[PptSource]:
    for citation in citations:
        yield PptSource(key=f"news:{citation.document_version_id}", source_type="\ub274\uc2a4\u00b7\uacf5\uc2dd \ubc1c\ud45c", title=citation.document_title or citation.source_name or "\ub274\uc2a4\u00b7\uacf5\uc2dd \ubc1c\ud45c \uc790\ub8cc", publisher=citation.source_name, published_at=citation.published_at)
    for reference in wiki_references:
        yield PptSource(key=f"wiki:{reference.wiki_version_id or reference.wiki_page_id}", source_type="\ub0b4\ubd80 Wiki", title=reference.wiki_title or "\ub0b4\ubd80 Wiki \uc790\ub8cc")


def _add_cover_slide(presentation: Presentation, document: PptReportDocument) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    _fill_background(slide, BRAND_NAVY)
    _rectangle(slide, 0, 0, .22, 7.5, BRAND_ORANGE); _rectangle(slide, .22, 0, .09, 7.5, BRAND_GOLD); _rectangle(slide, 9.2, 6.1, 2.7, .08, BRAND_ORANGE)
    _add_logo(slide, left=10.35, top=.66, height=.42)
    _text(slide, 1, 1.28, 7.2, .7, DEFAULT_PPT_TITLE, 31, True, WHITE)
    _text(slide, 1, 2.28, 7, .95, document.subtitle, 19, False, RGBColor(220, 227, 234))
    _rectangle(slide, 1, 4.55, 1.15, .05, BRAND_GOLD); _text(slide, 1, 4.9, 1.15, .28, "\uae30\uc900\uc77c", 11, True, RGBColor(185, 199, 211))
    _text(slide, 1, 5.2, 3.1, .45, _format_header_date_korean(document.report_date), 19, True, WHITE)
    _text(slide, 1, 6.55, 4.5, .25, "SK hynix Industry Trend Curation", 10, False, RGBColor(185, 199, 211))


def _add_no_data_slide(presentation: Presentation, document: PptReportDocument) -> None:
    slide = _new_content_slide(presentation, "\uc624\ub298\uc758 \ud575\uc2ec \uc694\uc57d", document.layout)
    _text(slide, 1, 2.8, 8.4, .4, "\ubd84\uc11d \uac00\ub2a5\ud55c \uc8fc\uc694 \uc774\uc288\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.", 22, True, BRAND_NAVY)
    _text(slide, 1, 3.35, 7.8, .36, "\uc644\ub8cc\ub41c \ubcf4\uace0\uc11c \uc139\uc158\uc774 \uc0dd\uc131\ub418\uba74 \ud575\uc2ec \uc774\uc288\uc640 \ucd9c\ucc98\ub97c \uc790\ub3d9\uc73c\ub85c \uad6c\uc131\ud569\ub2c8\ub2e4.", 15, False, BRAND_MUTED)


def _add_agenda_slide(presentation: Presentation, document: PptReportDocument) -> None:
    slide = _new_content_slide(presentation, "\ube0c\ub9ac\ud551 \uad6c\uc131", document.layout)
    for index, label in enumerate(("\uc624\ub298\uc758 \ud575\uc2ec \uc694\uc57d", "\uc8fc\uc694 \uc774\uc288 \ud55c\ub208\uc5d0 \ubcf4\uae30", "\ud575\uc2ec \uc774\uc288\ubcc4 \ubd84\uc11d", "\uce74\ud14c\uace0\ub9ac\ubcc4 \ub3d9\ud5a5", "\uc885\ud569 \uc2dc\uc0ac\uc810", "\uc804\uccb4 \ucd9c\ucc98"), 1):
        row, col = divmod(index - 1, 3); left, top = .95 + col * 4, 1.65 + row * 2.05
        _rectangle(slide, left, top, 3.55, 1.45, WHITE, BRAND_LINE)
        _text(slide, left+.25, top+.22, .4, .3, f"{index:02d}", 13, True, BRAND_ORANGE)
        _text(slide, left+.25, top+.63, 2.85, .35, label, 18, True, BRAND_NAVY)


def _add_today_summary_slide(presentation: Presentation, document: PptReportDocument, sections: list[PptSection]) -> None:
    slide = _new_content_slide(presentation, "\uc624\ub298\uc758 \ud575\uc2ec \uc694\uc57d", document.layout)
    selected = sections[:document.layout.max_summary_issues]; count = len(selected); width = 3.55 if count <= 3 else 2.2; gap = .24 if count <= 3 else .15
    left = (13.333 - (count * width + (count - 1) * gap)) / 2
    for index, section in enumerate(selected, 1):
        _summary_card(slide, left, 1.65, width, 4.6, index, section); left += width + gap


def _summary_card(slide, left: float, top: float, width: float, height: float, index: int, section: PptSection) -> None:
    _rectangle(slide, left, top, width, height, WHITE, BRAND_LINE); _rectangle(slide, left, top, width, .09, BRAND_ORANGE if index == 1 else BRAND_GOLD)
    _text(slide, left+.22, top+.27, .35, .25, f"{index:02d}", 11, True, BRAND_ORANGE); _text(slide, left+.65, top+.27, width-.85, .25, f"[{section.category}]", 10, True, BRAND_MUTED)
    _text(slide, left+.22, top+.78, width-.44, .85, _shorten(section.title, 42), 18 if width > 3 else 14, True, BRAND_NAVY)
    _text(slide, left+.22, top+1.92, width-.44, 1.45, _shorten(section.current_summary or _first(section.implications) or section.title, 80 if width > 3 else 52), 14 if width > 3 else 12, False, BRAND_TEXT)
    _rectangle(slide, left+.22, top+height-.78, width-.44, .01, BRAND_LINE); _text(slide, left+.22, top+height-.57, width-.44, .22, f"\uc911\uc694\ub3c4  {_importance_label(section.importance_score)}", 11, True, BRAND_ORANGE)


def _add_issue_overview_slide(presentation: Presentation, document: PptReportDocument, sections: list[PptSection]) -> None:
    slide = _new_content_slide(presentation, "\uc8fc\uc694 \uc774\uc288 \ud55c\ub208\uc5d0 \ubcf4\uae30", document.layout); visible = sections[:document.layout.max_overview_issues]
    headers, widths = ("\uc911\uc694\ub3c4", "\uce74\ud14c\uace0\ub9ac", "\uc8fc\uc694 \uc774\uc288", "\uc601\ud5a5 \ubc29\ud5a5", "\uc2dc\uac04 \ubc94\uc704"), (1.1, 1.65, 5.9, 1.45, 1.35)
    _table_row(slide, .85, 1.48, widths, headers, fill=BRAND_NAVY, color=WHITE, bold=True, font_size=11)
    height = min(.48, 4.9 / max(1, len(visible)))
    for index, section in enumerate(visible):
        _table_row(slide, .85, 1.93 + index * height, widths, (_importance_label(section.importance_score), section.category, _shorten(section.title, 52), _impact_label(section.impact_direction), _time_label(section.time_horizon)), fill=WHITE if index % 2 == 0 else BRAND_MIST, color=BRAND_TEXT, bold=False, font_size=11, height=height)


def _add_issue_analysis_slides(presentation: Presentation, document: PptReportDocument, index: int, section: PptSection, numbers: dict[str, int]) -> None:
    facts = list(section.key_facts[:3]) or list(section.historical_context[:2]); meaning = list(section.implications[:2]) or [section.current_summary or "\ud655\uc778\ub41c \uc758\ubbf8\uac00 \uc5c6\uc2b5\ub2c8\ub2e4."]
    impact = list(section.implications[:3]) or [section.current_summary or "SK\ud558\uc774\ub2c9\uc2a4 \uc601\ud5a5\uc740 \ucd94\uac00 \ud655\uc778\uc774 \ud544\uc694\ud569\ub2c8\ub2e4."]; watch = list(section.watch_points[:3]) or list(section.historical_context[:2])
    dense = sum(len(item) for item in facts + meaning + impact + watch) > 920
    if dense:
        _add_issue_analysis_slide(presentation, document, index, section, numbers, facts, meaning, (), (), "\uc0ac\uc2e4\uacfc \uc758\ubbf8")
        _add_issue_analysis_slide(presentation, document, index, section, numbers, (), (), impact, watch, "\uc601\ud5a5\uacfc \ud655\uc778 \uc0ac\ud56d")
    else:
        _add_issue_analysis_slide(presentation, document, index, section, numbers, facts, meaning, impact, watch, None)


def _add_issue_analysis_slide(presentation: Presentation, document: PptReportDocument, index: int, section: PptSection, numbers: dict[str, int], facts: list[str], meaning: list[str], impact: list[str], watch: list[str], continuation: str | None) -> None:
    title = f"ISSUE {index:02d}. {_shorten(section.title, 56)}" + (f" - {continuation}" if continuation else "")
    slide = _new_content_slide(presentation, title, document.layout); _text(slide, .85, 1.18, 10.8, .25, _issue_meta(section), 11, True, BRAND_MUTED)
    for (heading, items), (left, top) in zip((("\uc0ac\uc2e4", facts), ("\uc758\ubbf8", meaning), ("SK\ud558\uc774\ub2c9\uc2a4 \uc601\ud5a5", impact), ("\ub2e4\uc74c \ud655\uc778 \uc0ac\ud56d", watch)), ((.85, 1.62), (6.78, 1.62), (.85, 3.83), (6.78, 3.83))):
        _analysis_panel(slide, left, top, 5.7, 1.87, heading, items, document.layout)
    _text(slide, .85, 6.18, 11.35, .22, _source_caption(section, numbers), document.layout.source_font_size, False, BRAND_MUTED)


def _analysis_panel(slide, left: float, top: float, width: float, height: float, heading: str, items: list[str], layout: PptLayout) -> None:
    _rectangle(slide, left, top, width, height, WHITE, BRAND_LINE); _text(slide, left+.2, top+.18, width-.4, .25, heading, 13, True, BRAND_ORANGE)
    if items: _bullet_text(slide, left+.2, top+.58, width-.38, height-.72, [_shorten(item, 115) for item in items[:3]], layout.body_font_size)
    else: _text(slide, left+.2, top+.72, width-.4, .28, "\ud574\ub2f9 \uc5c6\uc74c", 13, False, BRAND_MUTED)


def _add_category_trend_slide(presentation: Presentation, document: PptReportDocument, sections: list[PptSection], categories: tuple[str, ...]) -> None:
    slide = _new_content_slide(presentation, "\uce74\ud14c\uace0\ub9ac\ubcc4 \ub3d9\ud5a5", document.layout)
    for position, category in enumerate(categories):
        top = 1.42 + position * 1.75; matched = [section for section in sections if section.category == category][:3]
        _rectangle(slide, .85, top, 11.6, 1.46, WHITE, BRAND_LINE); _text(slide, 1.08, top+.19, 1.7, .25, category, 15, True, BRAND_NAVY)
        if not matched: _text(slide, 3, top+.22, 3, .25, "\uc8fc\uc694 \ub3d9\ud5a5 \uc5c6\uc74c", 14, False, BRAND_MUTED); continue
        _bullet_text(slide, 3, top+.15, 5.55, .92, [_shorten(item.title, 48) for item in matched], 13)
        _text(slide, 8.85, top+.18, 2.95, .19, "\ud575\uc2ec \ubcc0\ud654", 10, True, BRAND_ORANGE); _text(slide, 8.85, top+.48, 2.95, .68, _shorten(matched[0].current_summary or _first(matched[0].implications) or matched[0].title, 92), 12, False, BRAND_TEXT)


def _add_implications_slide(presentation: Presentation, document: PptReportDocument, sections: list[PptSection]) -> None:
    slide = _new_content_slide(presentation, "\uc885\ud569 \uc2dc\uc0ac\uc810", document.layout)
    opportunity = _unique_items(section.implications for section in sections if section.impact_direction == "\uae30\ud68c") or _unique_items(section.implications for section in sections[:2])
    risk = _unique_items(section.implications for section in sections if section.impact_direction == "\uc704\ud5d8") or ["\uacbd\uc7c1\uc0ac \uacf5\uae09 \ud655\ub300\uc640 \uc218\uc728 \ubcc0\ud654\uac00 \uc2dc\uc7a5 \uade0\ud615\uc5d0 \ubbf8\uce58\ub294 \uc601\ud5a5\uc744 \uc810\uac80"]
    monitoring = _unique_items(section.watch_points for section in sections)
    for index, (heading, items, accent) in enumerate((("\uae30\ud68c", opportunity, BRAND_ORANGE), ("\uc704\ud5d8", risk, BRAND_NAVY), ("\uc9c0\uc18d \uad00\ucc30", monitoring, BRAND_GOLD))):
        left = .85 + index * 3.93; _rectangle(slide, left, 1.52, 3.63, 3.82, WHITE, BRAND_LINE); _rectangle(slide, left, 1.52, 3.63, .08, accent)
        _text(slide, left+.22, 1.8, 3.15, .3, heading, 17, True, BRAND_NAVY); _bullet_text(slide, left+.22, 2.28, 3.12, 2.67, [_shorten(item, 95) for item in items[:4]], 13)
    _rectangle(slide, .85, 5.75, 11.5, .55, RGBColor(255, 248, 239)); _text(slide, 1.05, 5.9, 11.05, .2, _overall_judgment(sections), 14, True, BRAND_NAVY, align=PP_ALIGN.CENTER)


def _add_source_slides(presentation: Presentation, document: PptReportDocument, sources: list[PptSource]) -> None:
    if not sources: return
    numbers = _source_numbers(sources)
    for page, chunk in enumerate(_chunked(sources, 8), 1):
        slide = _new_content_slide(presentation, "\uc804\uccb4 \ucd9c\ucc98" if page == 1 else f"\uc804\uccb4 \ucd9c\ucc98 ({page})", document.layout); widths = (.75, 1.85, 6.95, 1.65)
        _table_row(slide, .85, 1.46, widths, ("\ubc88\ud638", "\ucd9c\ucc98", "\uc81c\ubaa9", "\ubc1c\ud589\uc77c"), fill=BRAND_NAVY, color=WHITE, bold=True, font_size=11)
        for row, source in enumerate(chunk):
            values = (str(numbers[source.key]), source.source_type if source.source_type == "\ub0b4\ubd80 Wiki" else (source.publisher or source.source_type), _shorten(source.title, 68), _shorten(source.published_at or "-", 16))
            _table_row(slide, .85, 1.91 + row * .52, widths, values, fill=WHITE if row % 2 == 0 else BRAND_MIST, color=BRAND_TEXT, bold=False, font_size=10, height=.52)


def _new_content_slide(presentation: Presentation, title: str, layout: PptLayout):
    slide = presentation.slides.add_slide(presentation.slide_layouts[6]); _fill_background(slide, BRAND_MIST); _text(slide, .85, .54, 11.55, .38, title, layout.slide_title_font_size, True, BRAND_NAVY); return slide


def _add_common_chrome(presentation: Presentation, document: PptReportDocument) -> None:
    for number, slide in enumerate(presentation.slides, 1):
        if number == 1: continue
        _text(slide, .85, .16, 1.6, .2, _format_header_date_compact(document.report_date), 10, True, BRAND_MUTED); _text(slide, 10.45, .16, .72, .2, "MyWiki", 10, True, BRAND_NAVY, align=PP_ALIGN.RIGHT); _add_logo(slide, left=11.31, top=.11, height=.22)
        _rectangle(slide, .85, .42, 11.6, .012, BRAND_LINE); _rectangle(slide, .85, 6.78, 11.6, .012, BRAND_LINE); _text(slide, .85, 6.94, 4.2, .18, "SK hynix Industry Trend Curation", 9, False, BRAND_MUTED); _text(slide, 12.02, 6.94, .3, .18, str(number), 9, True, BRAND_MUTED, align=PP_ALIGN.RIGHT)


def _table_row(slide, left: float, top: float, widths: tuple[float, ...], values: tuple[str, ...], *, fill: RGBColor, color: RGBColor, bold: bool, font_size: int, height: float = .45) -> None:
    cursor = left
    for width, value in zip(widths, values):
        _rectangle(slide, cursor, top, width, height, fill, BRAND_LINE); _text(slide, cursor+.08, top+.1, width-.16, height-.1, value, font_size, bold, color, valign=MSO_VERTICAL_ANCHOR.MIDDLE); cursor += width


def _rectangle(slide, left: float, top: float, width: float, height: float, fill: RGBColor, line: RGBColor | None = None) -> None:
    shape = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height)); shape.fill.solid(); shape.fill.fore_color.rgb = fill
    if line is None: shape.line.fill.background()
    else: shape.line.color.rgb = line


def _text(slide, left: float, top: float, width: float, height: float, text: str, font_size: int | float, bold: bool, color: RGBColor, *, align: PP_ALIGN = PP_ALIGN.LEFT, valign: MSO_VERTICAL_ANCHOR = MSO_VERTICAL_ANCHOR.TOP) -> None:
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height)); frame = box.text_frame; frame.clear(); frame.word_wrap = True; frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0; frame.vertical_anchor = valign
    paragraph = frame.paragraphs[0]; paragraph.alignment = align; run = paragraph.add_run(); run.text = text; run.font.name = DEFAULT_PPT_FONT_NAME; run.font.size = Pt(font_size); run.font.bold = bold; run.font.color.rgb = color


def _bullet_text(slide, left: float, top: float, width: float, height: float, items: list[str], font_size: int | float) -> None:
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height)); frame = box.text_frame; frame.clear(); frame.word_wrap = True; frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    for index, item in enumerate(items[:6]):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph(); paragraph.text = item; paragraph.level = 0; paragraph.bullet = True; paragraph.font.name = DEFAULT_PPT_FONT_NAME; paragraph.font.size = Pt(font_size); paragraph.font.color.rgb = BRAND_TEXT; paragraph.space_after = Pt(3)


def _resolve_logo_path() -> Path | None:
    value = os.environ.get(PPT_LOGO_ENV)
    if value and Path(value).exists(): return Path(value)
    return DEFAULT_PPT_LOGO_PATH if DEFAULT_PPT_LOGO_PATH.exists() else None


def _add_logo(slide, *, left: float, top: float, height: float) -> None:
    path = _resolve_logo_path()
    if path is not None: slide.shapes.add_picture(str(path), Inches(left), Inches(top), height=Inches(height))


def _fill_background(slide, color: RGBColor) -> None:
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb = color


def _ordered_sections(sections: tuple[PptSection, ...]) -> list[PptSection]:
    return [section for _, section in sorted(enumerate(sections), key=lambda item: (-(item[1].importance_score or -1), item[0], item[1].title))]


def _collect_sources(sections: list[PptSection]) -> list[PptSource]:
    seen: set[str] = set(); output: list[PptSource] = []
    for section in sections:
        for source in section.sources:
            if source.key and source.key not in seen: seen.add(source.key); output.append(source)
    return output


def _source_numbers(sources: list[PptSource]) -> dict[str, int]: return {source.key: index for index, source in enumerate(sources, 1)}
def _source_caption(section: PptSection, numbers: dict[str, int]) -> str:
    used = [str(numbers[source.key]) for source in section.sources[:3] if source.key in numbers]
    return "\ucd9c\ucc98  " + ("  ".join(f"\u2460 {number}" for number in used) if used else "\ubcf4\uace0\uc11c \uc218\uc9d1 \uc790\ub8cc")
def _issue_meta(section: PptSection) -> str:
    score = f" {section.importance_score}\uc810" if section.importance_score is not None else ""
    return f"[{section.category}]  \uc911\uc694\ub3c4 {_importance_label(section.importance_score)}{score}  |  \uc601\ud5a5 {_impact_label(section.impact_direction)}  |  {_time_label(section.time_horizon)}"
def _importance_label(score: int | None) -> str: return "\ubbf8\ud3c9\uac00" if score is None else "\ub192\uc74c" if score >= 70 else "\ubcf4\ud1b5" if score >= 40 else "\ub0ae\uc74c"
def _impact_label(value: str | None) -> str: return {"\uae30\ud68c":"\uae0d\uc815", "\uc704\ud5d8":"\ubd80\uc815", "\ud63c\ud569":"\ubcf5\ud569", "\uc911\ub9bd":"\uc911\ub9bd"}.get(value or "", "\uc911\ub9bd")
def _time_label(value: str | None) -> str: return {"\uc989\uc2dc":"\ub2e8\uae30", "\ub2e8\uae30":"\ub2e8\uae30", "\uc911\uae30":"\uc911\uae30", "\uc7a5\uae30":"\uc7a5\uae30"}.get(value or "", "\uc911\uae30")
def _format_header_date_korean(value: str) -> str:
    parsed = _parse_date_text(value); return f"{parsed.year}\ub144 {parsed.month}\uc6d4 {parsed.day}\uc77c" if parsed else value
def _format_header_date_compact(value: str) -> str:
    parsed = _parse_date_text(value); return parsed.strftime("%Y.%m.%d") if parsed else value
def _parse_date_text(value: str) -> date | None:
    try: return date.fromisoformat((value or "").strip().split("T", 1)[0].replace(".", "-"))
    except ValueError: return None
def _shorten(value: str, limit: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit: return text
    for separator in (". ", "\ub2e4. ", "; ", ", "):
        cut = text.rfind(separator, 0, limit - 1)
        if cut >= limit // 2: return text[:cut + (1 if separator == "\ub2e4. " else 0)].rstrip()
    return text[:limit - 1].rstrip() + "\u2026"
def _first(values: tuple[str, ...]) -> str | None: return values[0] if values else None
def _unique_items(groups: Iterable[Iterable[str]]) -> list[str]:
    output: list[str] = []; seen: set[str] = set()
    for group in groups:
        for item in group:
            normalized = " ".join(item.split())
            if normalized and normalized not in seen: seen.add(normalized); output.append(normalized)
    return output
def _overall_judgment(sections: list[PptSection]) -> str:
    top = sections[0]; direction = "\uae30\ud68c\uac00 \ud655\ub300\ub418\uace0 \uc788\uc2b5\ub2c8\ub2e4" if top.impact_direction == "\uae30\ud68c" else "\uacbd\uc7c1\u00b7\uc218\uc694 \ubcc0\ud654\ub97c \uba74\ubc00\ud788 \uc810\uac80\ud574\uc57c \ud569\ub2c8\ub2e4"
    return f"{_shorten(top.title, 42)}\ub97c \uc911\uc2ec\uc73c\ub85c \uc0b0\uc5c5 \ubcc0\ud654\uac00 \uc9c4\ud589 \uc911\uc774\uba70, {direction}."
def _chunked(values: list[PptSource], size: int) -> Iterable[list[PptSource]]:
    for index in range(0, len(values), size): yield values[index:index + size]
