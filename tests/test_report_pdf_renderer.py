from io import BytesIO

from pypdf import PdfReader

from src.analysis.interface import EvidenceRef, SectionDraft
from src.report.pdf_renderer import (
    PdfReportDocument,
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
    decomposed = "한글 ✓ 😀"
    normalized = normalize_pdf_text(decomposed)

    assert normalized.startswith("한글")
    assert "[check]" in normalized
    assert "[emoji]" in normalized


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
    body = "한글 본문입니다. 수율 개선과 생산 확대가 동시에 진행됩니다."
    evidence = "엔비디아향 HBM 출하가 늘고 있습니다."
    assert "한글 본문" in repr(body)

    document = PdfReportDocument(
        title=f"일일 산업 동향 보고서 {REPORT_RENDERER_VERSION}",
        subtitle="sk-요약-2026-08-03",
        generated_at="2026-08-03T09:00:00+09:00",
        version=7,
        sections=(
            build_daily_report_pdf_document(
                report_key="unused",
                version=1,
                sections=[
                    SectionDraft(
                        category="공급망·생산",
                        title="HBM 양산 확대",
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

    assert "일일 산업 동향 보고서" in extracted
    assert "HBM 양산 확대" in extracted
    assert "한글 본문입니다." in extracted
    assert "생산 확대가 동시에 진행됩니다." in extracted
    assert "엔비디아향 HBM 출하가 늘고 있습니다." in extracted
