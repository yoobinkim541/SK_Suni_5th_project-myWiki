from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class WorkspaceSettings:
    workspace_id: str
    wiki_update_cycle_minutes: int
    data_refresh_cycle_minutes: int
    chat_retention_days: Optional[int]
    last_wiki_refresh_at: Optional[str]
    last_data_refresh_at: Optional[str]
    updated_at: str
