from __future__ import annotations

from src.analysis import repository


def test_get_supabase_disables_http2(monkeypatch):
    captured = {}

    def fake_create_client(url, key, options=None):
        captured["url"] = url
        captured["key"] = key
        captured["options"] = options
        return object()

    repository.get_supabase.cache_clear()
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")
    monkeypatch.setattr(repository, "create_client", fake_create_client)

    repository.get_supabase()

    http_client = captured["options"].httpx_client
    pool = http_client._transport._pool
    assert pool._http1 is True
    assert pool._http2 is False

    http_client.close()
    repository.get_supabase.cache_clear()
