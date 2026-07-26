from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..analysis.interface import SectionDraft


@dataclass
class Report:
    id: str
    workspace_id: str
    report_key: str
    version: int
    status: str


def create_report(
    workspace_id: str, report_key: str, report_type: str, sections: list[SectionDraft]
) -> Report:
    """
    reports에 새 버전을 INSERT하고(UPDATE 아님), status='completed'인 섹션만
    report_sections로 저장한다. 동일 report_key의 이전 버전은 그대로 남겨둔다.
    """
    raise NotImplementedError


def render_artifact(report_id: str, artifact_type: str, version: int) -> str:
    """
    report_sections를 모아 markdown/pdf 등으로 렌더링하고 Storage에 업로드한 뒤
    artifacts에 기록한다. object_key 규칙:
    {workspace_id}/reports/{report_id}/{artifact_type}/v{version}.{ext}
    반환값은 생성된 object_key.
    """
    raise NotImplementedError
