"""파이프라인 테스트 공용 픽스처."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fake_supabase import FakeSupabase

from src.collectors import fetchers
from src.collectors.interface import register_source
from src.pipeline_common import db
from src.pipeline_common.models import RawFetchResult

ARTICLE_HTML = """<!doctype html>
<html lang="ko">
  <head>
    <title>SK하이닉스 HBM4 양산</title>
    <meta property="article:published_time" content="2026-07-21T09:00:00+09:00">
  </head>
  <body>
    <nav>메뉴 · 로그인 · 광고</nav>
    <article>
      <h1>SK하이닉스 HBM4 양산</h1>
      <p>{body}</p>
    </article>
    <footer>ⓒ 2026 테스트뉴스</footer>
  </body>
</html>
"""

# script만 있는 문서. 노이즈 제거 후 본문이 비어 정제가 실패한다.
EMPTY_HTML = b"<html><body><script>var a = 1;</script><style>p{}</style></body></html>"


@pytest.fixture
def supabase() -> FakeSupabase:
    """FakeSupabase를 배치 클라이언트로 주입한다."""
    client = FakeSupabase()
    db.set_client(client)
    yield client
    db.reset_client()


@pytest.fixture
def workspace_id() -> UUID:
    return uuid4()


@pytest.fixture
def other_workspace_id() -> UUID:
    return uuid4()


@pytest.fixture
def source_id(supabase: FakeSupabase, workspace_id: UUID) -> UUID:
    return register_source(
        workspace_id,
        name="테스트 RSS",
        source_type="rss",
        base_url="https://example.com/feed.xml",
        config={"request_delay_sec": 0},
    )


class StubFeed:
    """외부 요청 없이 collect()에 넘길 원문을 지정한다."""

    def __init__(self) -> None:
        self.items: list[RawFetchResult] = []
        self.skip_reasons: dict[str, int] = {}

    def set_article(
        self,
        url: str = "https://example.com/news/1",
        title: str = "SK하이닉스 HBM4 양산",
        body: str = "SK하이닉스가 HBM4 양산을 시작했다.",
        content_type: str = "text/html",
        raw: bytes | None = None,
    ) -> None:
        self.items = [
            RawFetchResult(
                source_name="테스트 RSS",
                url=url,
                fetched_at=datetime.now(timezone.utc),
                content_type=content_type,
                body=raw if raw is not None else ARTICLE_HTML.format(body=body).encode("utf-8"),
                title_hint=title,
                published_at_hint=datetime(2026, 7, 21, 0, 0, tzinfo=timezone.utc),
            )
        ]


@pytest.fixture
def feed(monkeypatch: pytest.MonkeyPatch) -> StubFeed:
    """source_type='rss' 수집기를 스텁으로 교체한다."""
    stub = StubFeed()

    def fetcher(source: dict, request) -> fetchers.FetchOutcome:
        outcome = fetchers.FetchOutcome()
        outcome.items = list(stub.items)
        outcome.skip_reasons = dict(stub.skip_reasons)
        return outcome

    monkeypatch.setitem(fetchers._REGISTRY, "rss", fetcher)
    stub.set_article()
    return stub
