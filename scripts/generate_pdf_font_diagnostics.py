from __future__ import annotations

import hashlib
import json
import logging
import unicodedata
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.analysis.interface import EvidenceRef, SectionDraft
from src.report.pdf_renderer import (
    PdfReportDocument,
    PdfSection,
    REPORT_RENDERER_VERSION,
    normalize_pdf_text,
    render_daily_report_pdf,
)
from src.report.storage import build_report_artifact_object_key, build_report_artifact_storage_key

OUTPUT_DIR = Path("output/pdf")
REPORT_DIR = Path("output/pdf/diagnostics")
PROJECT_FONT_DIR = Path("assets/fonts")
NANUM_REGULAR = PROJECT_FONT_DIR / "NanumGothic-Regular.ttf"
NANUM_BOLD = PROJECT_FONT_DIR / "NanumGothic-Bold.ttf"
MALGUN_REGULAR = Path(r"C:\Windows\Fonts\malgun.ttf")
MALGUN_BOLD = Path(r"C:\Windows\Fonts\malgunbd.ttf")
TEST_TEXT = "한글 NFC 테스트: 한글, SK하이닉스, 공급망, 수율, 계약, 체크 ✓, 이모지 😀"
TEST_BODY = "SK하이닉스의 HBM 생산 확대와 수율 개선이 동시에 진행되고 있습니다.\n엔비디아향 출하 대응을 위해 공급망 투자도 확대되었습니다."
TEST_EVIDENCE = "SK하이닉스는 HBM 양산 능력과 공급 대응 역량을 강화하고 있다."

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")


def _register_font_set(prefix: str, regular_path: Path, bold_path: Path) -> tuple[str, str]:
    regular_name = f"{prefix}-Regular"
    bold_name = f"{prefix}-Bold"
    if regular_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))
    if bold_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
    pdfmetrics.registerFontFamily(prefix, normal=regular_name, bold=bold_name)
    return regular_name, bold_name


def _canvas_pdf(path: Path, regular_path: Path, bold_path: Path, prefix: str) -> bytes:
    regular_name, bold_name = _register_font_set(prefix, regular_path, bold_path)
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(path.stem)
    c.setFont(bold_name, 16)
    c.drawString(20 * mm, 270 * mm, normalize_pdf_text("Canvas Test 제목"))
    c.setFont(regular_name, 12)
    c.drawString(20 * mm, 255 * mm, normalize_pdf_text(TEST_TEXT))
    c.drawString(20 * mm, 245 * mm, normalize_pdf_text("REPORTLAB-TTF-V3 | Footer 샘플"))
    c.save()
    pdf_bytes = buffer.getvalue()
    path.write_bytes(pdf_bytes)
    return pdf_bytes


def _paragraph_pdf(path: Path) -> bytes:
    regular_name, bold_name = _register_font_set("DiagNanumParagraph", NANUM_REGULAR, NANUM_BOLD)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("DiagTitle", parent=styles["Title"], fontName=bold_name, fontSize=18, leading=24, wordWrap="CJK", textColor=colors.black)
    body_style = ParagraphStyle("DiagBody", parent=styles["BodyText"], fontName=regular_name, fontSize=11, leading=19, wordWrap="CJK")
    story = [
        Paragraph(normalize_pdf_text("Paragraph Test 제목"), title_style),
        Spacer(1, 4 * mm),
        Paragraph(normalize_pdf_text(TEST_TEXT), body_style),
        Spacer(1, 4 * mm),
        Paragraph(normalize_pdf_text(TEST_BODY), body_style),
    ]
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    path.write_bytes(pdf_bytes)
    return pdf_bytes


def _full_report_pdf(path: Path) -> bytes:
    section = PdfSection(
        category=normalize_pdf_text("공급망·생산"),
        title=normalize_pdf_text("HBM 양산 확대와 공급망 투자"),
        body=normalize_pdf_text(TEST_BODY),
        confidence_label="high",
        evidences=(
            type("E", (), {"document_version_id": normalize_pdf_text("ko-doc-1"), "quoted_text": normalize_pdf_text(TEST_EVIDENCE), "relevance_score": 0.93})(),
        ),
    )
    document = PdfReportDocument(
        title=normalize_pdf_text(f"일일 산업 동향 보고서 {REPORT_RENDERER_VERSION}"),
        subtitle=normalize_pdf_text("daily-trends-2026-08-03-ttf-v3"),
        generated_at=normalize_pdf_text("2026-08-03T09:00:00+09:00"),
        version=4,
        sections=(section,),
    )
    pdf_bytes = render_daily_report_pdf(document)
    path.write_bytes(pdf_bytes)
    return pdf_bytes


def _inspect_pdf(path: Path, pdf_bytes: bytes) -> dict[str, object]:
    reader = PdfReader(BytesIO(pdf_bytes))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    embedded = []
    font_names = []
    for page_index, page in enumerate(reader.pages, start=1):
        resources = page.get("/Resources")
        if resources is None:
            continue
        fonts = resources.get("/Font") if hasattr(resources, "get") else None
        if fonts is None:
            continue
        for font_resource, font_ref in fonts.get_object().items():
            font_obj = font_ref.get_object()
            base_font = str(font_obj.get("/BaseFont"))
            font_names.append({"page": page_index, "resource": str(font_resource), "base_font": base_font})
            descriptor_ref = font_obj.get("/FontDescriptor")
            if descriptor_ref is not None:
                descriptor = descriptor_ref.get_object()
                if descriptor.get("/FontFile2") is not None:
                    embedded.append({"page": page_index, "resource": str(font_resource), "base_font": base_font})
    return {
        "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "embedded_fontfile2": embedded,
        "font_names": font_names,
        "pypdf_extract": extracted,
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    raw = TEST_TEXT
    normalized = normalize_pdf_text(raw)
    input_info = {
        "input_repr": repr(raw),
        "normalized_repr": repr(normalized),
        "nfc_changed": unicodedata.normalize("NFC", raw) != raw,
        "sanitized_changed": normalized != raw,
    }

    files: dict[str, Path] = {
        "malgun_canvas": OUTPUT_DIR / "malgun-canvas-test.pdf",
        "nanum_canvas": OUTPUT_DIR / "nanum-canvas-test.pdf",
        "nanum_paragraph": OUTPUT_DIR / "nanum-paragraph-test.pdf",
        "nanum_full_report": OUTPUT_DIR / "nanum-full-report-test.pdf",
    }

    malgun_bytes = _canvas_pdf(files["malgun_canvas"], MALGUN_REGULAR, MALGUN_BOLD, "DiagMalgun")
    nanum_canvas_bytes = _canvas_pdf(files["nanum_canvas"], NANUM_REGULAR, NANUM_BOLD, "DiagNanumCanvas")
    nanum_paragraph_bytes = _paragraph_pdf(files["nanum_paragraph"])
    nanum_full_bytes = _full_report_pdf(files["nanum_full_report"])

    object_key = build_report_artifact_object_key(
        workspace_id="ws-ttf-v3",
        report_id="report-2026-08-03",
        artifact_type="pdf",
        version=4,
        extension="pdf",
    )
    storage_key = build_report_artifact_storage_key(
        workspace_id="ws-ttf-v3",
        report_id="report-2026-08-03",
        artifact_type="pdf",
        version=4,
        extension="pdf",
    )
    object_path = OUTPUT_DIR / object_key.replace("/", "__")
    object_path.write_bytes(nanum_full_bytes)

    report = {
        "input": input_info,
        "object_key": object_key,
        "storage_key": storage_key,
        "object_path": str(object_path),
        "files": {
            "malgun-canvas-test.pdf": _inspect_pdf(files["malgun_canvas"], malgun_bytes),
            "nanum-canvas-test.pdf": _inspect_pdf(files["nanum_canvas"], nanum_canvas_bytes),
            "nanum-paragraph-test.pdf": _inspect_pdf(files["nanum_paragraph"], nanum_paragraph_bytes),
            "nanum-full-report-test.pdf": _inspect_pdf(files["nanum_full_report"], nanum_full_bytes),
            "object-key-copy": _inspect_pdf(object_path, object_path.read_bytes()),
        },
    }
    report_path = REPORT_DIR / "pdf-font-diagnostics.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report_path)


if __name__ == "__main__":
    main()
