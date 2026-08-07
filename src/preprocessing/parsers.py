"""
원문 -> Markdown 정제와 content_hash 계산 (명세 §2-1).

이 단계는 요약하지 않는다. 형식 변환·노이즈 제거까지가 범위이고
분류·요약·신뢰도는 analysis의 책임이다 (프로젝트 지침 §2-5).

content_hash 계산 규칙
    대상     정제된 Markdown 본문 (원문 바이트가 아니다).
             상용구 제거(boilerplate.strip_boilerplate) 결과가 그대로 해시 대상이다 —
             저장하는 Markdown과 해시하는 Markdown은 언제나 같은 문자열이다.
    알고리즘 SHA-256, 소문자 hex 64자
    정규화   ① 개행을 \\n으로 통일 ② 각 줄 끝 공백 제거 ③ 문서 앞뒤 공백 제거
             ④ 연속 빈 줄이 2줄 이상이면 2줄로 축약 ⑤ UTF-8 인코딩 후 해시
    제외     제목·발행일·URL은 해시에 넣지 않는다 (메타 변경이 새 버전을 만들지 않게)

원문 바이트 기준을 택하지 않은 이유: 광고·내비게이션·타임스탬프 위젯만 바뀌어도
매 수집마다 새 버전이 쌓인다. 정제본 기준이면 실질 내용이 바뀔 때만 버전이 늘어난다.

단 정제본 기준만으로는 부족했다. 2026-08-07 실측에서 document_versions 1,445행 중
452행이 관련기사·추천기사 블록 변경만으로 생긴 버전이었다. 태그 단위 노이즈 제거
(_NOISE_TAGS)는 <nav>·<footer>만 걷어내고, 본문 아래에 <div>로 붙는 관련기사 목록은
그대로 통과시키기 때문이다. 그래서 boilerplate.strip_boilerplate를 추가했다.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from ..pipeline_common.models import ParsedContent
from ..pipeline_common.timeutil import parse_datetime  # noqa: F401 - 하위 호환 re-export
from .boilerplate import strip_boilerplate

# '{parser}-v{major}.{minor}' (명세 §8 확정)
PARSER_VERSIONS = {
    # v1.1: 상용구(관련기사·추천기사) 제거를 넣었다. 같은 원문이라도 v1.0과 해시가 다르다.
    # 이 값은 재해시 마이그레이션의 커서이기도 하다 (scripts/run_pipeline.py --rehash).
    "html": "html-v1.1",
    "pdf": "pdf-v1.0",
    "json": "json-v1.0",
    "text": "text-v1.0",
}

# 정제 대상에서 통째로 걷어내는 태그
_NOISE_TAGS = (
    "script", "style", "noscript", "iframe", "svg",
    "nav", "header", "footer", "aside",
)

# 내용은 남기고 태그만 벗기는 태그. ASP.NET WebForms 계열 국내 언론사(예: 뉴스토마토)는
# 페이지 전체를 <form id="aspnetForm">으로 감싸므로, form을 _NOISE_TAGS처럼 decompose()하면
# 본문까지 통째로 사라져 "정제 결과가 비어 있다"로 실패한다.
_UNWRAP_TAGS = ("form",)

# 본문일 가능성이 높은 순서. class/id 기반 선택자를 태그 선택자보다 먼저 둔다 —
# 일부 언론사(예: 한경)는 <article>이 광고·메뉴까지 포함하는 바깥 wrapper라서
# <article>을 먼저 매칭하면 본문 대신 그 wrapper 전체가 뽑힌다.
_MAIN_SELECTORS = (".article-body", "#content", "[role=main]", "article", "main")

# 본문 후보로 인정할 최소 텍스트 길이. 이보다 짧으면 빈 껍데기로 보고 다음 후보로 넘어간다.
_MIN_MAIN_TEXT_LEN = 50

# 이 크기를 넘는 HTML이 텍스트를 하나도 안 남기면 JS 렌더링 페이지로 본다.
# 관측된 실패분: news.google.com 582KB, 조선일보 236KB, biz.sbs.co.kr 10KB.
# 가장 작은 sbs가 걸리도록 5KB로 잡았다. 어차피 사유 힌트일 뿐이라 판정이 틀려도
# 정제 결과(실패)는 달라지지 않는다 — 그래서 보수적으로 좁히기보다 넓게 잡는다.
_SPA_MIN_BODY_BYTES = 5_000

_BLANK_LINES = re.compile(r"\n{4,}")
_HANGUL = re.compile(r"[가-힣]")
_ASCII_LETTER = re.compile(r"[A-Za-z]")


class ParseError(Exception):
    """정제 실패. preprocess()가 잡아서 pipeline_jobs에 남긴다."""


# ------------------------------------------------------------
# 해시
# ------------------------------------------------------------


def normalize_markdown(markdown: str) -> str:
    """content_hash 계산 전 정규화 ①~④. 저장하는 Markdown도 이 결과를 쓴다."""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")  # ①
    text = "\n".join(line.rstrip() for line in text.split("\n"))  # ②
    text = text.strip()  # ③
    text = _BLANK_LINES.sub("\n\n\n", text)  # ④ 빈 줄은 최대 2줄
    return text


def compute_content_hash(markdown: str) -> str:
    """정규화된 Markdown의 SHA-256 소문자 hex 64자 ⑤."""
    return hashlib.sha256(normalize_markdown(markdown).encode("utf-8")).hexdigest()


# ------------------------------------------------------------
# 공통 유틸
# ------------------------------------------------------------


def detect_language(text: str) -> str | None:
    """
    BCP-47 소문자 2자. 판별 실패 시 None.

    반도체·한국어 뉴스가 대상이라 한글 포함 여부로 가른다.
    별도 라이브러리를 쓰지 않아 결과가 결정적이다.
    """
    sample = text[:4000]
    if _HANGUL.search(sample):
        return "ko"
    if _ASCII_LETTER.search(sample):
        return "en"
    return None


def decode_body(body: bytes, content_type: str = "") -> str:
    """content_type의 charset -> utf-8 -> cp949 순으로 시도한다."""
    match = re.search(r"charset=([\w\-]+)", content_type or "", re.IGNORECASE)
    candidates = [match.group(1)] if match else []
    candidates += ["utf-8", "cp949"]
    for encoding in candidates:
        try:
            return body.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", errors="replace")


def _base_content_type(content_type: str) -> str:
    return (content_type or "").split(";")[0].strip().lower()


# ------------------------------------------------------------
# 파서별 구현
# ------------------------------------------------------------


def _empty_reason_hint(name: str, body: bytes) -> str:
    """
    정제 결과가 빈 이유를 사유별로 구분해 남긴다.

    이걸 나누지 않으면 "고칠 수 있는 실패"와 "정적 수집으로는 원리상 불가능한 실패"가
    한 문자열로 뭉쳐서, 실패율을 봐도 손댈 곳이 있는지 판단할 수 없다.
    2026-08-05 시점 13건 중 12건이 아래 SPA 경로였다
    (조선일보 계열 8, news.google.com 3, biz.sbs.co.kr 1).
    """
    if name != "html" or not body:
        return ""
    # 원문은 큰데 텍스트가 거의 없으면 본문을 JS로 그리는 페이지다.
    if len(body) >= _SPA_MIN_BODY_BYTES:
        return " — 본문이 JS로 렌더링되는 페이지로 보임(정적 수집 불가)"
    return ""


def _parse_html(body: bytes, content_type: str) -> tuple[str, str | None, str | None]:
    """(markdown, title, published_at_raw)."""
    from bs4 import BeautifulSoup
    from markdownify import markdownify

    html = decode_body(body, content_type)
    soup = BeautifulSoup(html, "html.parser")

    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
    if not title and soup.h1:
        title = soup.h1.get_text(strip=True)

    published_raw = None
    for attrs in (
        {"property": "article:published_time"},
        {"property": "og:article:published_time"},
        {"itemprop": "datePublished"},
        {"name": "date"},
    ):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            published_raw = meta["content"]
            break
    if not published_raw:
        time_tag = soup.find("time")
        if time_tag and time_tag.get("datetime"):
            published_raw = time_tag["datetime"]

    for tag in soup(list(_NOISE_TAGS)):
        tag.decompose()
    for tag in soup(list(_UNWRAP_TAGS)):
        tag.unwrap()

    # 매칭되는 것이 아니라 **내용이 있는** 첫 노드를 고른다.
    # 비즈니스포스트(businesspost.co.kr)는 빈 <div id="content">를 두고 본문을 그 밖에
    # 두는데, 매칭만 보면 이 빈 노드가 잡혀 soup.body 폴백을 가로막는다.
    # 실제로 그 사이트 기사가 "정제 결과가 비어 있다"로 실패했다 (2026-08-03).
    node = None
    for selector in _MAIN_SELECTORS:
        found = soup.select_one(selector)
        if found is not None and len(found.get_text(strip=True)) >= _MIN_MAIN_TEXT_LEN:
            node = found
            break
    if node is None:
        node = soup.body or soup

    # 관련기사·추천기사 블록을 걷어낸다. markdownify 이전이어야 한다 —
    # strip=["a"]가 앵커를 텍스트로 만들어버려서 Markdown에는 링크 정보가 없다.
    node, _ = strip_boilerplate(node)

    markdown = markdownify(str(node), heading_style="ATX", strip=["a"])
    return markdown, title, published_raw


def _parse_pdf(body: bytes) -> tuple[str, str | None, str | None]:
    from io import BytesIO

    # pypdf는 requirements.txt에 없다. MVP 소스에 PDF가 없어 일부러 뺐다.
    #
    # BaseException까지 잡는 이유: 미설치는 ImportError지만, 설치가 깨진 경우
    # (예: pypdf -> cryptography -> rust 바인딩 실패) pyo3가 PanicException을 던진다.
    # 이건 Exception이 아니라 BaseException 상속이라 preprocess()의 except Exception에
    # 걸리지 않고, 문서 1건 때문에 배치 전체가 죽는다. 여기서 ParseError로 바꿔
    # job에 사유가 남게 한다 (명세 §1-3).
    try:
        from pypdf import PdfReader
    except (KeyboardInterrupt, SystemExit):  # 중단 신호는 그대로 통과시킨다
        raise
    except BaseException as exc:  # noqa: BLE001
        raise ParseError(
            f"pypdf를 불러올 수 없다 ({type(exc).__name__}: {exc}). "
            "PDF 소스를 쓰려면 requirements.txt에 pypdf를 추가하고 설치 상태를 확인한다"
        ) from exc

    try:
        reader = PdfReader(BytesIO(body))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:  # noqa: BLE001 - pypdf 예외 종류가 다양하다
        raise ParseError(f"PDF를 읽을 수 없다: {exc}") from exc

    title = None
    try:
        meta = reader.metadata
        if meta and meta.title:
            title = str(meta.title).strip()
    except Exception:  # noqa: BLE001 - 메타는 없어도 그만
        title = None
    return "\n\n".join(p.strip() for p in pages if p.strip()), title, None


def _parse_json(body: bytes, content_type: str) -> tuple[str, str | None, str | None]:
    text = decode_body(body, content_type)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError(f"JSON을 읽을 수 없다: {exc}") from exc

    if not isinstance(payload, dict):
        return f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```", None, None

    title = payload.get("title") or payload.get("headline")
    published_raw = payload.get("published_at") or payload.get("pubDate")
    for key in ("content", "body", "description", "summary", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value, title, published_raw
    dumped = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"```json\n{dumped}\n```", title, published_raw


def _parse_text(body: bytes, content_type: str) -> tuple[str, str | None, str | None]:
    return decode_body(body, content_type), None, None


_PARSER_BY_CONTENT_TYPE = {
    "text/html": "html",
    "application/xhtml+xml": "html",
    "application/pdf": "pdf",
    "application/json": "json",
    "text/plain": "text",
    "text/markdown": "text",
}


def parser_name_for(content_type: str) -> str:
    """content_type -> 파서 이름. 지원하지 않으면 ParseError."""
    name = _PARSER_BY_CONTENT_TYPE.get(_base_content_type(content_type))
    if name is None:
        raise ParseError(f"지원하지 않는 content_type: {content_type!r}")
    return name


def parse(
    body: bytes,
    content_type: str,
    *,
    title_hint: str | None = None,
    published_at_hint: datetime | None = None,
    fetched_at: datetime | None = None,
) -> ParsedContent:
    """
    원문 바이트를 ParsedContent로 정제한다. 실패는 ParseError.

    title은 NOT NULL이라 원문 -> 힌트 -> 고정 문구 순으로 반드시 채운다
    (출처 라벨 품질이 여기에 종속된다. 명세 §7-2).
    """
    name = parser_name_for(content_type)
    if not body:
        raise ParseError("원문이 비어 있다")

    if name == "html":
        markdown, title, published_raw = _parse_html(body, content_type)
    elif name == "pdf":
        markdown, title, published_raw = _parse_pdf(body)
    elif name == "json":
        markdown, title, published_raw = _parse_json(body, content_type)
    else:
        markdown, title, published_raw = _parse_text(body, content_type)

    markdown = normalize_markdown(markdown)
    if not markdown:
        raise ParseError(f"정제 결과가 비어 있다 (parser={name}){_empty_reason_hint(name, body)}")

    published_at = parse_datetime(published_raw) or published_at_hint
    if published_at is not None and published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    resolved_title = (title or title_hint or "").strip() or "(제목 없음)"

    return ParsedContent(
        markdown=markdown,
        content_hash=compute_content_hash(markdown),
        title=resolved_title[:500],  # documents.title VARCHAR(500)
        published_at=published_at,
        language=detect_language(markdown),
        parser_version=PARSER_VERSIONS[name],
    )
