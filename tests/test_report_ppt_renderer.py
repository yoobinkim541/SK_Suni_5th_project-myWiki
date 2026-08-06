from __future__ import annotations

from datetime import date
from io import BytesIO

from pptx import Presentation

from src.analysis.importance_models import ImpactDirection, TimeHorizon
from src.analysis.models import Category
from src.report.models import ReportCitationDraft, ReportSectionDraft, ReportSectionStatus
from src.report.ppt_renderer import (
    DEFAULT_PPT_TITLE,
    build_daily_report_ppt_document,
    build_daily_report_ppt_filename,
    render_daily_report_ppt,
)

K_TITLE = "\uc77c\uc77c \uc0b0\uc5c5 \ub3d9\ud5a5 \ub9de\ucda4 \ubcf4\uace0\uc11c"
K_SECTION = "HBM \uc218\uc694 \ud655\ub300\uc640 \uacf5\uae09\ub9dd \ud22c\uc790 \uac00\uc18d"
K_BODY = "\uad6d\ub0b4 \uba54\ubaa8\ub9ac \uc81c\uc870\uc0ac\uc640 \uacf5\uae09\ub9dd \uae30\uc5c5\ub4e4\uc774 AI \uc11c\ubc84 \uc218\uc694 \uc99d\uac00\uc5d0 \ub300\uc751\ud558\uae30 \uc704\ud574 \uc0dd\uc0b0\ub2a5\ub825 \ud655\uc7a5\uacfc \uc7a5\ube44 \ud22c\uc790\ub97c \ub3d9\uc2dc\uc5d0 \ucd94\uc9c4\ud558\uace0 \uc788\uc2b5\ub2c8\ub2e4."
K_EVIDENCE = "HBM \uc218\uc694 \ud655\ub300\uc5d0 \ub9de\ucdb0 \uad00\ub828 \uacf5\uae09\ub9dd \uc804\ubc18\uc5d0\uc11c \ud22c\uc790 \uc18d\ub3c4\uac00 \ube68\ub77c\uc9c0\uace0 \uc788\ub2e4."


def make_section(*, status: ReportSectionStatus = ReportSectionStatus.COMPLETED) -> ReportSectionDraft:
    return ReportSectionDraft(
        issue_key="issue-1",
        representative_analysis_result_id="analysis-1",
        category=Category.PRODUCT_TECHNOLOGY,
        importance_score=88,
        impact_direction=ImpactDirection.OPPORTUNITY,
        time_horizon=TimeHorizon.MID_TERM,
        title=K_SECTION,
        current_summary=K_BODY,
        key_facts=["\ud575\uc2ec \uc0ac\uc2e4 1", "\ud575\uc2ec \uc0ac\uc2e4 2"],
        implications=["SK\ud558\uc774\ub2c9\uc2a4 \uc218\ud61c\uc0ac \ud655\ub300"],
        watch_points=["\uad00\ucc30 \ud3ec\uc778\ud2b8"],
        news_citations=[
            ReportCitationDraft(
                analysis_result_id="analysis-1",
                document_version_id="doc-ver-1",
                citation_order=1,
                evidence_text=K_EVIDENCE,
                relevance_score=0.92,
            )
        ],
        status=status,
    )


def collect_ppt_text(pptx_bytes: bytes) -> str:
    presentation = Presentation(BytesIO(pptx_bytes))
    texts: list[str] = []
    for slide in presentation.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                text = shape.text.strip()
                if text:
                    texts.append(text)
    return "\n".join(texts)


def test_build_daily_report_ppt_document_uses_completed_sections_only() -> None:
    completed = make_section(status=ReportSectionStatus.COMPLETED)
    pending = make_section(status=ReportSectionStatus.DRAFTING)

    document = build_daily_report_ppt_document(
        report_key="daily-trends-2026-08-03",
        version=2,
        sections=[completed, pending],
        generated_at="2026-08-03T09:00:00+09:00",
        report_date=date(2026, 8, 3),
        title=K_TITLE,
    )

    assert document.title == K_TITLE
    assert document.subtitle == "AI 및 반도체 산업의 주요 변화를 이슈별로 정리한 데일리 브리핑"
    assert document.report_date == "2026-08-03"
    assert document.version == 2
    assert len(document.sections) == 1
    assert document.sections[0].title == K_SECTION


def test_build_daily_report_ppt_filename_normalizes_spaces() -> None:
    assert build_daily_report_ppt_filename(report_key="daily trends 2026-08-03", version=3) == "daily-trends-2026-08-03-v3.pptx"


def test_render_daily_report_ppt_returns_pptx_bytes() -> None:
    report_document = build_daily_report_ppt_document(
        report_key="daily-trends-2026-08-03",
        version=1,
        sections=[make_section()],
        generated_at="2026-08-03T09:00:00+09:00",
        report_date=date(2026, 8, 3),
        title=K_TITLE,
    )

    pptx_bytes = render_daily_report_ppt(report_document)
    text = collect_ppt_text(pptx_bytes)

    assert pptx_bytes[:2] == b"PK"
    assert DEFAULT_PPT_TITLE in text
    assert "MyWiki" in text
    assert "2026\ub144 8\uc6d4 3\uc77c" in text
    assert K_SECTION in text
    assert K_BODY in text
    assert "전체 출처" in text
    assert "daily-trends-2026-08-03" not in text
    assert "Format" not in text


def test_render_daily_report_ppt_prefers_report_date_over_generated_at() -> None:
    report_document = build_daily_report_ppt_document(
        report_key="daily-trends-2026-08-03",
        version=1,
        sections=[make_section()],
        generated_at="2026-08-02T23:30:00+00:00",
        report_date=date(2026, 8, 3),
    )

    pptx_bytes = render_daily_report_ppt(report_document)
    text = collect_ppt_text(pptx_bytes)

    assert "2026\ub144 8\uc6d4 3\uc77c" in text


def test_render_daily_report_ppt_creates_agenda_and_evidence_slides() -> None:
    report_document = build_daily_report_ppt_document(
        report_key="daily-trends-2026-08-03",
        version=1,
        sections=[make_section()],
        report_date=date(2026, 8, 3),
    )

    presentation = Presentation(BytesIO(render_daily_report_ppt(report_document)))

    assert len(presentation.slides) >= 4



def test_render_daily_report_ppt_uses_briefing_sequence_and_common_chrome() -> None:
    report_document = build_daily_report_ppt_document(
        report_key="daily:internal-id:2026-08-03",
        version=1,
        sections=[make_section()],
        report_date=date(2026, 8, 3),
    )

    presentation = Presentation(BytesIO(render_daily_report_ppt(report_document)))
    slide_text = ["\n".join(shape.text for shape in slide.shapes if hasattr(shape, "text")) for slide in presentation.slides]

    assert len(presentation.slides) == 8
    assert "오늘의 핵심 요약" in slide_text[1]
    assert "주요 이슈 한눈에 보기" in slide_text[2]
    assert "ISSUE 01." in slide_text[3]
    assert "카테고리별 동향" in slide_text[4]
    assert "종합 시사점" in slide_text[6]
    assert "전체 출처" in slide_text[7]
    assert all("2026.08.03" in text and "MyWiki" in text and "SK hynix Industry Trend Curation" in text for text in slide_text[1:])
    assert all("daily:internal-id:2026-08-03" not in text for text in slide_text)


def test_render_daily_report_ppt_hides_empty_sections() -> None:
    document = build_daily_report_ppt_document(
        report_key="daily-trends-2026-08-03",
        version=1,
        sections=[make_section(status=ReportSectionStatus.DRAFTING)],
        report_date=date(2026, 8, 3),
    )

    text = collect_ppt_text(render_daily_report_ppt(document))

    assert "분석 가능한 주요 이슈가 없습니다." in text
    assert "No completed sections available." not in text
    assert "Agenda" not in text
