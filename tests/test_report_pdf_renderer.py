from io import BytesIO

from pypdf import PdfReader

from src.analysis.interface import EvidenceRef, SectionDraft
from src.report.pdf_renderer import (
    PdfReportDocument,
    PdfSection,
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
