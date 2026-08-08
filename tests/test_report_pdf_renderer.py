from io import BytesIO

from pypdf import PdfReader

from src.analysis.interface import EvidenceRef, SectionDraft
from src.report.pdf_renderer import (
    PdfExecutiveSummaryLine,
    PdfReportDocument,
    PdfSection,
    PdfSourceLine,
    K_ALL_SOURCES,
    K_CATEGORIES,
    K_IMPLICATIONS,
    K_MONITORING,
    K_OPPORTUNITY,
    K_RISK,
    REPORT_RENDERER_VERSION,
    build_daily_report_pdf_document,
    build_daily_report_pdf_filename,
    normalize_pdf_text,
    render_daily_report_pdf,
)


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_build_daily_report_pdf_document_reuses_completed_sections() -> None:
    completed = SectionDraft(
        category="technology",
        title="HBM demand expansion",
        content="HBM investment and demand are expanding at the same time.",
        confidence_score=0.82,
        evidences=[
            EvidenceRef(
                document_version_id="doc-1",
                quoted_text="HBM demand is increasing quickly.",
                relevance_score=0.91,
            )
        ],
        status="completed",
    )
    skipped = SectionDraft(
        category="company",
        title="Incomplete section",
        content="",
        confidence_score=None,
        evidences=[],
        status="pending",
    )

    document = build_daily_report_pdf_document(
        report_key="daily-trends-2026-08-02",
        version=2,
        sections=[completed, skipped],
        generated_at="2026-08-02T09:00:00+00:00",
    )

    assert document.title == f"Daily Trend Report {REPORT_RENDERER_VERSION}"
    assert document.subtitle == "daily-trends-2026-08-02"
    assert document.version == 2
    assert len(document.sections) == 1
    assert document.sections[0].title == "HBM demand expansion"
    assert document.sections[0].confidence_label == "high"
    assert document.sections[0].evidences[0].document_version_id == "doc-1"


def test_build_daily_report_pdf_filename_normalizes_spaces() -> None:
    assert (
        build_daily_report_pdf_filename(
            report_key="daily trends 2026-08-02",
            version=3,
        )
        == "daily-trends-2026-08-02-v3.pdf"
    )


def test_normalize_pdf_text_applies_nfc_and_replaces_unsupported_chars() -> None:
    decomposed = "\u1112\u1161\u11ab \u2713 \U0001F600"
    normalized = normalize_pdf_text(decomposed)

    assert normalized == "\ud55c [check] [emoji]"


def test_render_daily_report_pdf_returns_pdf_bytes() -> None:
    document = build_daily_report_pdf_document(
        report_key="daily-trends-2026-08-02",
        version=1,
        sections=[
            SectionDraft(
                category="technology",
                title="HBM demand expansion",
                content="Demand keeps rising across AI memory supply chains.",
                confidence_score=0.82,
                evidences=[
                    EvidenceRef(
                        document_version_id="doc-1",
                        quoted_text="Demand keeps rising.",
                        relevance_score=0.91,
                    )
                ],
                status="completed",
            )
        ],
        generated_at="2026-08-02T09:00:00+00:00",
    )

    pdf_bytes = render_daily_report_pdf(document)
    extracted = _extract_text(pdf_bytes)

    assert pdf_bytes.startswith(b"%PDF")
    assert f"Daily Trend Report {REPORT_RENDERER_VERSION}" in extracted
    assert REPORT_RENDERER_VERSION in extracted
    assert "HBM demand expansion" in extracted
    assert "Demand keeps rising across AI memory supply chains." in extracted


def test_render_daily_report_pdf_preserves_korean_text_for_extraction() -> None:
    title = "\uc77c\uc77c \uc0b0\uc5c5 \ub3d9\ud5a5 \ubcf4\uace0\uc11c"
    body = "\ud55c\uae00 \ubcf8\ubb38\uc785\ub2c8\ub2e4. \uc218\uc728 \uac1c\uc120\uacfc \uc0dd\uc0b0 \uc548\uc815\ud654\uac00 \ub3d9\uc2dc\uc5d0 \uc9c4\ud589\ub429\ub2c8\ub2e4."
    evidence = "\uc5d4\ube44\ub514\uc544 HBM \ucd9c\ud558\uac00 \ub298\uace0 \uc788\uc2b5\ub2c8\ub2e4."

    document = PdfReportDocument(
        title=f"{title} {REPORT_RENDERER_VERSION}",
        subtitle="sk-report-2026-08-03",
        generated_at="2026-08-03T09:00:00+09:00",
        version=7,
        sections=(
            build_daily_report_pdf_document(
                report_key="unused",
                version=1,
                sections=[
                    SectionDraft(
                        category="supply-chain",
                        title="HBM \uc591\uc0b0 \uc548\uc815\ud654",
                        content=body,
                        confidence_score=0.91,
                        evidences=[
                            EvidenceRef(
                                document_version_id="ko-doc-1",
                                quoted_text=evidence,
                                relevance_score=0.88,
                            )
                        ],
                        status="completed",
                    )
                ],
            ).sections[0],
        ),
    )

    pdf_bytes = render_daily_report_pdf(document)
    extracted = _extract_text(pdf_bytes)

    assert title in extracted
    assert "HBM \uc591\uc0b0 \uc548\uc815\ud654" in extracted
    assert "\ud55c\uae00 \ubcf8\ubb38\uc785\ub2c8\ub2e4." in extracted
    assert "\uc0dd\uc0b0 \uc548\uc815\ud654\uac00 \ub3d9\uc2dc\uc5d0 \uc9c4\ud589\ub429\ub2c8\ub2e4." in extracted
    assert "\uc5d4\ube44\ub514\uc544 HBM \ucd9c\ud558\uac00 \ub298\uace0 \uc788\uc2b5\ub2c8\ub2e4." in extracted


def test_render_daily_report_pdf_splits_long_implications_without_layout_error() -> None:
    def _items(prefix: str) -> list[str]:
        return [
            f"- {prefix} detailed implication line {index:02d} keeps the full report content available for review and page splitting marker-{prefix}-{index:02d}"
            for index in range(90)
        ]

    body = "\n".join(
        [K_OPPORTUNITY, *_items("opportunity"), "", K_RISK, *_items("risk"), "", K_MONITORING, *_items("monitoring")]
    )
    document = PdfReportDocument(
        title="Daily Report",
        subtitle="2026-08-08",
        generated_at="2026-08-08T08:00:00+09:00",
        version=18,
        sections=(
            PdfSection(
                category="",
                title=K_IMPLICATIONS,
                body=body,
                confidence_label="",
                section_type="implications",
            ),
        ),
    )

    pdf_bytes = render_daily_report_pdf(document)
    reader = PdfReader(BytesIO(pdf_bytes))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 0
    assert len(reader.pages) >= 2
    assert K_IMPLICATIONS in extracted
    assert "marker-opportunity-89" in extracted
    assert "marker-risk-89" in extracted
    assert "marker-monitoring-89" in extracted



def test_render_daily_report_pdf_handles_long_issue_title_body_and_korean_bullets() -> None:
    long_title = "ISSUE 01. " + "SK\ud558\uc774\ub2c9\uc2a4 AI \uba54\ubaa8\ub9ac \ud22c\uc790 \ubc0f \uc6a9\uc778 \ud074\ub7ec\uc2a4\ud130 \uc0dd\uc0b0\ub2a5\ub825 \ud655\ub300 " * 4
    long_paragraph = " ".join(["\ud55c\uae00 \ubcf8\ubb38\uc774 \uc5ec\ub7ec \ud398\uc774\uc9c0\uc5d0 \uac78\ucc98 \uc790\uc5f0\uc2a4\ub7fd\uac8c \uc774\uc5b4\uc9d1\ub2c8\ub2e4" for _ in range(180)])
    body = "\n".join([
        "\uc0ac\uc2e4",
        "- SK\ud558\uc774\ub2c9\uc2a4 \uc6a9\uc778 \ubc0f \uccad\uc8fc \ud22c\uc790 \uc77c\uc815\uc744 \uc810\uac80\ud569\ub2c8\ub2e4.",
        "- \ud55c\uae00 bullet \uc815\uc0c1 \ucd9c\ub825 \ud655\uc778",
        "\uc758\ubbf8",
        long_paragraph,
        "SK\ud558\uc774\ub2c9\uc2a4 \uc601\ud5a5",
        "- \uc2dc\uc7a5 \uc9c0\ubc30\ub825\uc744 \uac15\ud654\ud558\ub294 \ud22c\uc790 \uc2e0\ud638\ub85c \ud574\uc11d\ub429\ub2c8\ub2e4.",
        "\ub2e4\uc74c \ud655\uc778 \uc0ac\ud56d",
        "- marker-long-issue-end",
    ])
    document = PdfReportDocument(
        title="\uc77c\uc77c \uc0b0\uc5c5 \ub3d9\ud5a5 \ubcf4\uace0\uc11c",
        subtitle="2026-08-08",
        generated_at="2026-08-08T08:00:00+09:00",
        version=28,
        sections=(
            PdfSection(category="\uacf5\uae09\ub9dd\u00b7\uc0dd\uc0b0", title=long_title, body=body, confidence_label="", section_type="issue", importance_score=96, reliability_score=90, impact_direction="\ud63c\ud569", time_horizon="\uc7a5\uae30"),
        ),
    )

    pdf_bytes = render_daily_report_pdf(document)
    reader = PdfReader(BytesIO(pdf_bytes))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(reader.pages) >= 2
    assert "SK\ud558\uc774\ub2c9\uc2a4" in extracted
    assert "\ud55c\uae00 bullet \uc815\uc0c1 \ucd9c\ub825" in extracted
    assert "marker-long-issue-end" in extracted
    assert "1 /" in extracted


def test_render_daily_report_pdf_does_not_leave_issue_title_without_metadata() -> None:
    filler = "\n".join(f"\uc0ac\uc804 \uc694\uc57d \ubb38\ub2e8 {index:02d} " + "\ubcf8\ubb38 " * 20 for index in range(38))
    issue_title = "ISSUE 02. \ud398\uc774\uc9c0 \ud558\ub2e8\uc5d0\uc11c \ud63c\uc790 \ub0a8\uc9c0 \uc54a\uc544\uc57c \ud558\ub294 \uc774\uc288 \uc81c\ubaa9"
    document = PdfReportDocument(
        title="Daily Report",
        subtitle="2026-08-08",
        generated_at="2026-08-08T08:00:00+09:00",
        version=28,
        sections=(
            PdfSection(category="", title="\uc624\ub298\uc758 \ud575\uc2ec \uc694\uc57d", body=filler, confidence_label="", section_type="executive"),
            PdfSection(category="\uc2dc\uc7a5\u00b7\uacbd\uc601", title=issue_title, body="\uc0ac\uc2e4\n- first-content-marker\n\uc758\ubbf8\n- \ud398\uc774\uc9c0 \ubd84\ud560 \ud655\uc778", confidence_label="", section_type="issue", importance_score=88),
        ),
    )

    reader = PdfReader(BytesIO(render_daily_report_pdf(document)))
    pages = [page.extract_text() or "" for page in reader.pages]
    issue_pages = [text for text in pages if issue_title[:30] in text]

    assert issue_pages
    assert any("\uc911\uc694\ub3c4" in page and "first-content-marker" in page for page in issue_pages)


def test_render_daily_report_pdf_handles_six_category_cards_with_empty_values() -> None:
    body = "\n".join([
        "\uc81c\ud488\u00b7\uae30\uc220", "- \uc8fc\uc694 \ub3d9\ud5a5 \uc5c6\uc74c",
        "\uacbd\uc7c1\uc0ac", "- \uc8fc\uc694 \ub3d9\ud5a5 \uc5c6\uc74c",
        "\uace0\uac1d\u00b7\uc218\uc694\uc0b0\uc5c5", "- AI \uc11c\ubc84 \uc218\uc694 \uc99d\uac00",
        "\uacf5\uae09\ub9dd\u00b7\uc0dd\uc0b0", "- \uc6a9\uc778 \ud074\ub7ec\uc2a4\ud130 \uc77c\uc815 \uc810\uac80",
        "\uc815\ucc45\u00b7\uaddc\uc81c", "- \uc8fc\uc694 \ub3d9\ud5a5 \uc5c6\uc74c",
        "\uc2dc\uc7a5\u00b7\uacbd\uc601", "- \uac00\uaca9 \ubcc0\ub3d9\uc131 \uc810\uac80",
    ])
    document = PdfReportDocument(
        title="Daily Report",
        subtitle="2026-08-08",
        generated_at="2026-08-08T08:00:00+09:00",
        version=28,
        sections=(PdfSection(category="", title=K_CATEGORIES, body=body, confidence_label="", section_type="categories"),),
    )

    extracted = _extract_text(render_daily_report_pdf(document))

    for category in ("\uc81c\ud488\u00b7\uae30\uc220", "\uacbd\uc7c1\uc0ac", "\uace0\uac1d\u00b7\uc218\uc694\uc0b0\uc5c5", "\uacf5\uae09\ub9dd\u00b7\uc0dd\uc0b0", "\uc815\ucc45\u00b7\uaddc\uc81c", "\uc2dc\uc7a5\u00b7\uacbd\uc601"):
        assert category in extracted
    assert "AI \uc11c\ubc84 \uc218\uc694 \uc99d\uac00" in extracted


def test_render_daily_report_pdf_handles_long_sources_and_missing_metadata() -> None:
    long_title = "SK\ud558\uc774\ub2c9\uc2a4 \uc0b0\uc5c5 \ub3d9\ud5a5 \ucd9c\ucc98 \uc81c\ubaa9 " * 20
    document = PdfReportDocument(
        title="Daily Report",
        subtitle="2026-08-08",
        generated_at="2026-08-08T08:00:00+09:00",
        version=28,
        sections=(
            PdfSection(
                category="",
                title=K_ALL_SOURCES,
                body="",
                confidence_label="",
                section_type="sources",
                source_rows=(
                    PdfSourceLine(source_type="\ub274\uc2a4", source_name="Example News", title=long_title, published_at="", url="https://example.com/very/long/url/that/should/not/be/printed"),
                    PdfSourceLine(source_type="\ub0b4\ubd80 Wiki", source_name="", title="", published_at="", url=None),
                ),
            ),
        ),
    )

    extracted = _extract_text(render_daily_report_pdf(document))

    assert "NEWS" in extracted
    assert "MYWIKI" in extracted
    assert "Example News" in extracted
    assert "\ub9c1\ud06c" in extracted
    assert "https://example.com/very/long" not in extracted
