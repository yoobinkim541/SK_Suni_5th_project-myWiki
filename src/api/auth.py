"""
Supabase Auth JWT 검증.
프론트에서 Authorization: Bearer <supabase access_token>으로 넘어온 토큰을
Supabase 프로젝트의 JWT secret으로 검증해서 user_id(profiles.id)를 뽑아낸다.
"""
from __future__ import annotations

import os

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import db

bearer_scheme = HTTPBearer(auto_error=False)


def _decode_supabase_jwt(token: str) -> dict:
    secret = os.environ["SUPABASE_JWT_SECRET"]
    try:
        return jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")
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

    return profile
