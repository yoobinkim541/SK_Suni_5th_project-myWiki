"""수집 출처(sources)를 등록하는 배치 진입점.

register_source()가 (workspace_id, name)으로 이미 있는 출처는 그대로 두므로
몇 번을 실행해도 안전하다 (src/collectors/interface.py 참조).

사용법:
    python scripts/register_sources.py --dry-run   # 등록될 목록만 확인
    python scripts/register_sources.py              # 실제 등록
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.collectors.interface import register_source
from src.pipeline_common import repository
from src.pipeline_common.db import get_client

# 멘토 관심 키워드: SK하이닉스·삼성전자·Micron·NVIDIA·TSMC / HBM·DRAM·NAND·AI 서버·메모리 가격·수출 규제.
# HBM/DRAM/SK하이닉스는 이미 아래 목록에 있어 중복 추가하지 않는다.
NAVER_QUERIES = ["SK하이닉스", "HBM", "DRAM", "반도체 수출", "삼성전자", "NAND", "AI 서버", "메모리 가격", "수출 규제"]
GNEWS_QUERIES = ["semiconductor", "HBM memory", "SK Hynix", "Micron", "NVIDIA", "TSMC"]
GOOGLE_RSS_QUERIES = ["SK하이닉스"]
# DART는 검색어가 아니라 회사 단위다 — Open API가 corp_code + 날짜 범위로만 조회되고
# 자유 검색어를 지원하지 않는다(fetch_disclosure()도 config.corp_code만 읽음).
# (회사명, DART 고유번호 8자리) 쌍으로 등록한다. Micron/NVIDIA/TSMC는 해외기업이라 DART에
# corp_code가 없다 — 뉴스(GNEWS_QUERIES)로만 커버한다.
DART_COMPANIES = [
    ("SK하이닉스", "00164779"),
    ("삼성전자", "00126380"),
    ("SK스퀘어", "01596425"),
    ("한미반도체", "00161383"),
]


def google_news_rss_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko"


def build_source_specs() -> list[dict]:
    specs: list[dict] = []
    for query in NAVER_QUERIES:
        specs.append(
            {
                "name": f"네이버 - {query}",
                "source_type": "news",
                "base_url": None,
                "config": {"provider": "naver", "query": query},
            }
        )
    for query in GNEWS_QUERIES:
        specs.append(
            {
                "name": f"GNews - {query}",
                "source_type": "news",
                "base_url": None,
                "config": {"provider": "gnews", "query": query, "lang": "en"},
            }
        )
    for query in GOOGLE_RSS_QUERIES:
        specs.append(
            {
                "name": f"구글 RSS - {query}",
                "source_type": "rss",
                "base_url": google_news_rss_url(query),
                "config": None,
            }
        )
    for name, corp_code in DART_COMPANIES:
        specs.append(
            {
                "name": f"DART - {name}",
                "source_type": "disclosure",
                "base_url": None,
                "config": {"corp_code": corp_code},
            }
        )
    return specs


def get_workspace_id() -> UUID:
    res = get_client().table("workspaces").select("id").eq("slug", "mywiki").single().execute()
    return UUID(res.data["id"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="등록될 목록만 출력하고 실제 등록은 하지 않는다"
    )
    args = parser.parse_args()

    workspace_id = get_workspace_id()
    specs = build_source_specs()

    rows: list[tuple[str, str, str]] = []
    for spec in specs:
        existing = repository.find_source_by_name(workspace_id, spec["name"])
        if args.dry_run:
            status = "기존" if existing else "신규(dry-run)"
            source_id = str(existing["id"]) if existing else "-"
        else:
            status = "기존" if existing else "신규"
            source_id = str(
                register_source(
                    workspace_id,
                    spec["name"],
                    spec["source_type"],
                    base_url=spec["base_url"],
                    config=spec["config"],
                )
            )
        rows.append((spec["name"], source_id, status))

    name_width = max(len(row[0]) for row in rows)
    id_width = max(len(row[1]) for row in rows)
    header = f"{'이름'.ljust(name_width)}  {'source_id'.ljust(id_width)}  상태"
    print(header)
    print("-" * len(header))
    for name, source_id, status in rows:
        print(f"{name.ljust(name_width)}  {source_id.ljust(id_width)}  {status}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
