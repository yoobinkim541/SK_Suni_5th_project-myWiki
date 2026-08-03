from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

load_dotenv()

from src.settings.models import WorkspaceSettings
from src.settings.service import (
    CHAT_RETENTION_DAYS_CHOICES,
    WIKI_UPDATE_CYCLE_MINUTES_CHOICES,
    get_workspace_settings,
    mark_wiki_refreshed,
    update_workspace_settings,
)
from src.settings import service as settings_service


@pytest.fixture(scope="module")
def workspace_id() -> str:
    if not os.environ.get("SUPABASE_URL") or not (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SECRET_KEY")
    ):
        pytest.skip("Supabase service credentials are not configured.")
    try:
        db = settings_service._get_client()
        res = db.table("workspaces").select("id").eq("slug", "mywiki").single().execute()
        return res.data["id"]
    except Exception as e:
        pytest.skip(f"Supabase connection failed (likely placeholder credentials): {type(e).__name__}")


def test_choices_match_check_constraints():
    assert WIKI_UPDATE_CYCLE_MINUTES_CHOICES == (30, 60, 180, 360, 720, 1440)
    assert CHAT_RETENTION_DAYS_CHOICES == (7, 30, 90)


def test_get_workspace_settings_returns_existing_row(workspace_id):
    settings = get_workspace_settings(workspace_id)
    assert isinstance(settings, WorkspaceSettings)
    assert settings.workspace_id == workspace_id
    assert settings.wiki_update_cycle_minutes in WIKI_UPDATE_CYCLE_MINUTES_CHOICES


def test_update_workspace_settings_changes_wiki_cycle(workspace_id):
    original = get_workspace_settings(workspace_id)
    try:
        updated = update_workspace_settings(workspace_id, wiki_update_cycle_minutes=60, updated_by=None)
        assert updated.wiki_update_cycle_minutes == 60
        refetched = get_workspace_settings(workspace_id)
        assert refetched.wiki_update_cycle_minutes == 60
    finally:
        update_workspace_settings(
            workspace_id, wiki_update_cycle_minutes=original.wiki_update_cycle_minutes, updated_by=None
        )


def test_update_workspace_settings_can_set_chat_retention_to_forever(workspace_id):
    original = get_workspace_settings(workspace_id)
    try:
        updated = update_workspace_settings(workspace_id, chat_retention_days=None, updated_by=None)
        assert updated.chat_retention_days is None
    finally:
        update_workspace_settings(
            workspace_id, chat_retention_days=original.chat_retention_days, updated_by=None
        )


def test_update_workspace_settings_without_chat_retention_leaves_it_unchanged(workspace_id):
    original = get_workspace_settings(workspace_id)
    try:
        update_workspace_settings(workspace_id, chat_retention_days=30, updated_by=None)
        updated = update_workspace_settings(workspace_id, wiki_update_cycle_minutes=180, updated_by=None)
        assert updated.chat_retention_days == 30  # 안 건드렸으니 유지
    finally:
        update_workspace_settings(
            workspace_id,
            wiki_update_cycle_minutes=original.wiki_update_cycle_minutes,
            chat_retention_days=original.chat_retention_days,
            updated_by=None,
        )


def test_mark_wiki_refreshed_sets_timestamp(workspace_id):
    mark_wiki_refreshed(workspace_id)
    settings = get_workspace_settings(workspace_id)
    assert settings.last_wiki_refresh_at is not None
