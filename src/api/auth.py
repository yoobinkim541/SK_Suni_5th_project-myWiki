"""
Supabase Auth JWT 검증.
프론트에서 Authorization: Bearer <supabase access_token>으로 넘어온 토큰을
Supabase 프로젝트의 JWKS(공개키 세트)로 검증해서 user_id(profiles.id)를 뽑아낸다.

Supabase 프로젝트가 JWT Signing Keys(비대칭, ES256)로 발급하는 토큰은 공유 비밀키가
없다 — SUPABASE_JWKS_URL에서 공개키를 받아 토큰 헤더의 kid로 맞는 키를 찾아 검증한다.
PyJWKClient가 JWKS 응답을 캐싱하므로 매 요청마다 다시 받아오지 않는다.
"""
from __future__ import annotations

import os
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from . import db

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def _get_jwk_client() -> PyJWKClient:
    return PyJWKClient(os.environ["SUPABASE_JWKS_URL"])


def _decode_supabase_jwt(token: str) -> dict:
    try:
        signing_key = _get_jwk_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid token: {e}")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")

    payload = _decode_supabase_jwt(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token missing sub")

    profile = db.get_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="profile not found")

    # 탈퇴 처리(soft_delete_profile) 이후에도 삭제 요청 당시 발급된 JWT가 만료 전까지는
    # 계속 유효할 수 있어, profiles.deleted_at을 여기서도 다시 막는다 — 탈퇴 API가 마지막에
    # auth 사용자 자체를 지우긴 하지만, 그 호출이 실패하거나 지연되는 경우의 방어선이다.
    if profile.get("deleted_at") is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="탈퇴한 계정입니다")

    return profile
