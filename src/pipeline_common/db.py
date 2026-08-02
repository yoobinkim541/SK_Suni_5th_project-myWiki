"""
배치용 Supabase 클라이언트.

배치는 SERVICE_ROLE_KEY로 접속해 RLS를 우회하므로,
모든 쿼리에 workspace_id를 애플리케이션이 직접 건다 (명세 §1-3).

`supabase` 패키지는 실제 접속이 필요할 때만 import한다.
테스트는 set_client()로 더블을 주입하고 패키지를 요구하지 않는다.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

# 반환 타입을 supabase.Client로 좁히지 않고 Any로 둔다.
# 테스트가 더블을 주입할 수 있어야 하고, 이 모듈이 supabase 패키지를
# import하지 않아야 패키지 없이도 테스트가 돈다.
_injected: Any | None = None


@lru_cache(maxsize=1)
def _create_client() -> Any:
    from supabase import create_client  # 지연 import: 테스트는 이 경로를 타지 않는다

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def get_client() -> Any:
    """주입된 클라이언트가 있으면 그것을, 없으면 환경변수로 만든 클라이언트를 반환."""
    if _injected is not None:
        return _injected
    return _create_client()


def set_client(client: Any) -> None:
    """테스트·배치 진입점에서 클라이언트를 주입한다."""
    global _injected
    _injected = client


def reset_client() -> None:
    """주입을 해제한다."""
    global _injected
    _injected = None


def is_unique_violation(exc: Exception) -> bool:
    """
    UNIQUE 제약 위반(PostgreSQL 23505) 여부.

    supabase-py는 버전에 따라 APIError / dict 형태로 코드를 노출해서,
    코드와 메시지 양쪽을 본다.
    """
    code = getattr(exc, "code", None)
    if code is None:
        details = getattr(exc, "args", None)
        if details and isinstance(details[0], dict):
            code = details[0].get("code")
    if str(code) == "23505":
        return True
    message = str(exc).lower()
    return "23505" in message or "duplicate key value" in message
