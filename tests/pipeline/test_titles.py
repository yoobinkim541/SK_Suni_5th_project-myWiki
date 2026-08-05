"""
제목 꼬리표 제거 테스트.

케이스는 전부 2026-08-05 시점 실제 수집분(documents 279건)에서 뽑았다.
당시 279건 중 149건(53.4%)이 꼬리표를 달고 있었고, 구글 뉴스 RSS 소스 2개는 100%였다.
"""
from __future__ import annotations

from uuid import UUID

import pytest
from conftest import StubFeed
from fake_supabase import FakeSupabase

from src.collectors.interface import collect
from src.pipeline_common.models import CollectRequest
from src.pipeline_common.titles import (
    TITLE_MAX_LEN,
    normalize_title,
    strip_publisher_suffix,
)
from src.preprocessing.interface import preprocess


@pytest.mark.parametrize(
    "raw, expected",
    [
        # 한 겹 — 가장 흔한 형태
        (
            "'주주들 안달인데' … SK하이닉스, 주주환원 내놓지 못하는 까닭은 - 뉴데일리",
            "'주주들 안달인데' … SK하이닉스, 주주환원 내놓지 못하는 까닭은",
        ),
        # 두 겹 — 원문 <title>이 이미 매체명으로 끝나는데 RSS가 또 붙인 경우
        (
            '"SK하이닉스, 주주환원으로 LTA 인정받을 것…목표가 400만원 유지" - 머니투데이 - 머니투데이',
            '"SK하이닉스, 주주환원으로 LTA 인정받을 것…목표가 400만원 유지"',
        ),
        # 두 겹 — 한글 매체명 다음에 영문 표기가 붙는다
        (
            "SK하이닉스, 샌디스크와 HBF 첫 표준 규격 공개 - 조선비즈 - Chosunbiz",
            "SK하이닉스, 샌디스크와 HBF 첫 표준 규격 공개",
        ),
        # 두 겹 — 두 번째가 도메인
        (
            '"SK하이닉스 저평가, 2배 더 간다"...월가 분석에 ADR 8% 급등 - 머니투데이 - mt.co.kr',
            '"SK하이닉스 저평가, 2배 더 간다"...월가 분석에 ADR 8% 급등',
        ),
        # 도메인만 붙은 형태 — 관측 최다(31건)
        (
            "글로벌 빅테크로 옮겨 붙은 K성과급 논란…마이크론 노조, 파업 카드 만지작 - v.daum.net",
            "글로벌 빅테크로 옮겨 붙은 K성과급 논란…마이크론 노조, 파업 카드 만지작",
        ),
        # 매체명 자체에 하이픈이 있는 경우. 꼬리에서 하이픈을 배제하면 이걸 놓친다
        (
            "삼성·SK하이닉스, HBM 너머 '차세대 AI 메모리' 주도권 경쟁 본격화 - g-enews.com",
            "삼성·SK하이닉스, HBM 너머 '차세대 AI 메모리' 주도권 경쟁 본격화",
        ),
        # 공백이 포함된 2단어 매체명
        ("SK하이닉스 신고가 경신 소식 정리 - KBS 뉴스", "SK하이닉스 신고가 경신 소식 정리"),
        ("SK하이닉스, 순현금 100조 쌓기 '미션 파서블' - 네이버 프리미엄콘텐츠", "SK하이닉스, 순현금 100조 쌓기 '미션 파서블'"),
        # 제목 끝이 대괄호로 끝나도 꼬리표는 그 뒤에 붙는다
        (
            "“SK하이닉스 흔든 진범 잡혔다”…다시 ‘300만닉스’ 갈까? [잇슈 머니] - v.daum.net",
            "“SK하이닉스 흔든 진범 잡혔다”…다시 ‘300만닉스’ 갈까? [잇슈 머니]",
        ),
    ],
)
def test_꼬리표를_제거한다(raw: str, expected: str) -> None:
    assert strip_publisher_suffix(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        # 실제 오탐 사례. 22자·4단어라 매체명으로 보지 않는다
        "Uttar Pradesh Semiconductor Policy, 2024 - Driving with the Times",
        # 구분자 앞뒤 공백이 없으면 합성어다
        "e-커머스 시장에서 반도체 수요가 늘고 있다",
        "HBM4-Pro 양산 일정이 앞당겨졌다",
        # 꼬리가 문장이면 매체명이 아니다
        "SK하이닉스 실적 발표 - 시장은 어떻게 반응했나?",
        # 꼬리에 쉼표가 있으면 매체명이 아니다
        "반도체 수출 증가 - 메모리, 파운드리 모두 상승",
        # 꼬리표가 없다
        "SK하이닉스, HBM4 양산 시작",
    ],
)
def test_매체명이_아니면_건드리지_않는다(raw: str) -> None:
    assert strip_publisher_suffix(raw) == raw


def test_세_겹은_두_번까지만_벗긴다() -> None:
    """상한이 없으면 제목 본체를 계속 갉아먹는다."""
    assert strip_publisher_suffix("반도체 시장 전망 분석 - 조선비즈 - Chosunbiz - chosun.com") == "반도체 시장 전망 분석 - 조선비즈"


def test_본체가_너무_짧아지면_멈춘다() -> None:
    """남는 부분이 10자 미만이면 꼬리표가 아니라 제목을 자른 것으로 본다."""
    assert strip_publisher_suffix("반도체 - 한국경제") == "반도체 - 한국경제"


def test_normalize_title_은_공백을_정리한다() -> None:
    assert normalize_title("SK하이닉스,   HBM4  양산   - 한국경제") == "SK하이닉스, HBM4 양산"


def test_normalize_title_은_길이를_제한한다() -> None:
    """documents.title은 VARCHAR(500)이다."""
    assert len(normalize_title("가" * 600)) == TITLE_MAX_LEN


def test_normalize_title_은_비면_fallback을_쓴다() -> None:
    """documents.title은 NOT NULL이라 빈 문자열을 넣을 수 없다."""
    assert normalize_title("", fallback="https://example.com/news/1") == "https://example.com/news/1"
    assert normalize_title("   ", fallback="대체 제목") == "대체 제목"


def test_normalize_title_은_멱등이다() -> None:
    """preprocess가 매 회차 호출해도 결과가 흔들리면 안 된다."""
    once = normalize_title("SK하이닉스, 샌디스크와 HBF 첫 표준 규격 공개 - 조선비즈 - Chosunbiz")
    assert normalize_title(once) == once


# ------------------------------------------------------------
# preprocess 배선 — 뽑은 제목이 documents.title까지 도달하는가
# ------------------------------------------------------------

# conftest의 ARTICLE_HTML은 <title>SK하이닉스 HBM4 양산</title>을 갖는다.
_CLEAN = "SK하이닉스 HBM4 양산"
_TAGGED = f"{_CLEAN} - 테스트뉴스"


def _title_in_db(supabase: FakeSupabase, document_id) -> str:
    rows = [r for r in supabase.rows("documents") if str(r["id"]) == str(document_id)]
    assert rows, "documents 행이 없다"
    return rows[0]["title"]


def test_preprocess가_collect의_꼬리표를_교정한다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed: StubFeed
) -> None:
    feed.set_article(title=_TAGGED)
    document_id = collect(CollectRequest(workspace_id=workspace_id, source_id=source_id))[0].document_id

    # collect는 RSS가 준 제목을 그대로 넣는다
    assert _title_in_db(supabase, document_id) == _TAGGED

    processed = preprocess(document_id)

    assert processed is not None
    assert _title_in_db(supabase, document_id) == _CLEAN
    # 하류가 받는 값도 교정돼 있어야 한다
    assert processed.title == _CLEAN


def test_내용이_같아도_제목은_교정한다(
    supabase: FakeSupabase, workspace_id: UUID, source_id: UUID, feed: StubFeed
) -> None:
    """dedup 경로(새 버전 없음)에서도 제목은 틀려 있을 수 있다."""
    feed.set_article(title=_CLEAN)
    document_id = collect(CollectRequest(workspace_id=workspace_id, source_id=source_id))[0].document_id
    first = preprocess(document_id)
    assert first is not None and first.is_new_version is True

    # 같은 본문을 꼬리표 붙은 제목으로 재수집 -> content_hash는 그대로다
    feed.set_article(title=_TAGGED)
    collect(CollectRequest(workspace_id=workspace_id, source_id=source_id))
    assert _title_in_db(supabase, document_id) == _TAGGED

    second = preprocess(document_id)

    assert second is not None
    assert second.is_new_version is False  # dedup 경로를 탔다
    assert _title_in_db(supabase, document_id) == _CLEAN


def test_제목_교정_실패는_정제를_죽이지_않는다(
    supabase: FakeSupabase,
    workspace_id: UUID,
    source_id: UUID,
    feed: StubFeed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_preprocess의 루프에는 예외 처리가 없다. 여기서 예외가 새면 배치가 통째로 죽는다."""
    from src.pipeline_common import repository

    feed.set_article(title=_TAGGED)
    document_id = collect(CollectRequest(workspace_id=workspace_id, source_id=source_id))[0].document_id

    def boom(*args, **kwargs):
        raise RuntimeError("update 실패")

    monkeypatch.setattr(repository, "update_document_meta", boom)

    processed = preprocess(document_id)

    # 버전은 정상적으로 만들어진다
    assert processed is not None
    assert processed.is_new_version is True
    # 사유는 job result에 남는다
    job = [
        r
        for r in supabase.rows("pipeline_jobs")
        if r.get("job_type") == "parse_document" and str(r.get("target_id")) == str(document_id)
    ][0]
    assert "제목 교정 실패" in (job["result"] or {}).get("title_error", "")
