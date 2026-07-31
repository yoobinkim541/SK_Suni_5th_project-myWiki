"""
문서 버전 번호 산출 (명세 §3-5).

collect()가 raw 경로를 만들 때, preprocess()가 행을 만들 때 양쪽이 호출하므로
어느 한쪽 모듈에 두면 상류 -> 하류 역의존이 생긴다. 그래서 공용 모듈에 둔다.
"""
from __future__ import annotations

from uuid import UUID

from . import repository


def next_document_version_no(document_id: UUID) -> int:
    """
    해당 문서의 다음 version_no. 버전이 없으면 1.

    사전조건: document_id는 workspace 필터를 거친 조회에서 얻은 값이어야 한다.
    이 함수는 workspace_id를 받지 않는다 — 내부 전용이고 반환값이 정수 하나라
    정보 노출 위험이 낮아 의도적으로 인자를 두지 않았다 (명세 §9-3).

    동시 실행 시 같은 값을 반환할 수 있으나 uq_dv_document_versionno가
    DB에서 차단하므로 정합은 유지된다.
    """
    latest = repository.latest_version(document_id)
    if latest is None:
        return 1
    return int(latest["version_no"]) + 1
