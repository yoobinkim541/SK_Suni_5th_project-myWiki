"""
src/api/auth.py의 JWT 검증 테스트.

Supabase 프로젝트가 JWT Signing Keys(비대칭, ES256)를 쓰면 공유 비밀키가 없다 —
SUPABASE_JWKS_URL에서 공개키를 받아 kid로 맞는 키를 찾아 검증해야 한다.
실제 네트워크(JWKS 엔드포인트) 없이 검증하기 위해, 테스트용 EC 키쌍을 직접
만들어서 서명한 토큰을 PyJWKClient 대신 주입한 가짜 signing key로 검증한다.
"""
from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from src.api import auth


@pytest.fixture
def ec_keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


def _make_token(private_key, *, audience: str = "authenticated", exp_delta: int = 3600, **claims) -> str:
    payload = {
        "sub": "user-1",
        "aud": audience,
        "exp": int(time.time()) + exp_delta,
        **claims,
    }
    return jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": "test-kid"})


class _FakeSigningKey:
    def __init__(self, key) -> None:
        self.key = key


class _FakeJWKClient:
    def __init__(self, public_key) -> None:
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        return _FakeSigningKey(self._public_key)


def test_decode_supabase_jwt_accepts_valid_es256_token(monkeypatch: pytest.MonkeyPatch, ec_keypair) -> None:
    private_key, public_key = ec_keypair
    monkeypatch.setattr(auth, "_get_jwk_client", lambda: _FakeJWKClient(public_key))
    token = _make_token(private_key)

    payload = auth._decode_supabase_jwt(token)

    assert payload["sub"] == "user-1"


def test_decode_supabase_jwt_rejects_wrong_signing_key(monkeypatch: pytest.MonkeyPatch, ec_keypair) -> None:
    """다른 키로 서명된 토큰(예: 탈취/위조)은 거부돼야 한다."""
    private_key, _ = ec_keypair
    wrong_public_key = ec.generate_private_key(ec.SECP256R1()).public_key()
    monkeypatch.setattr(auth, "_get_jwk_client", lambda: _FakeJWKClient(wrong_public_key))
    token = _make_token(private_key)

    with pytest.raises(HTTPException) as exc_info:
        auth._decode_supabase_jwt(token)
    assert exc_info.value.status_code == 401


def test_decode_supabase_jwt_rejects_expired_token(monkeypatch: pytest.MonkeyPatch, ec_keypair) -> None:
    private_key, public_key = ec_keypair
    monkeypatch.setattr(auth, "_get_jwk_client", lambda: _FakeJWKClient(public_key))
    token = _make_token(private_key, exp_delta=-60)

    with pytest.raises(HTTPException) as exc_info:
        auth._decode_supabase_jwt(token)
    assert exc_info.value.status_code == 401


def test_decode_supabase_jwt_rejects_wrong_audience(monkeypatch: pytest.MonkeyPatch, ec_keypair) -> None:
    private_key, public_key = ec_keypair
    monkeypatch.setattr(auth, "_get_jwk_client", lambda: _FakeJWKClient(public_key))
    token = _make_token(private_key, audience="something-else")

    with pytest.raises(HTTPException) as exc_info:
        auth._decode_supabase_jwt(token)
    assert exc_info.value.status_code == 401
