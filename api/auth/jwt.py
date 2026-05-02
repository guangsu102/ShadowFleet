from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from utils.config_parser import load_raw_config

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, _get_secret(), algorithm=ALGORITHM)


def create_refresh_token(data: dict[str, Any]) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, _get_secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[ALGORITHM])
        return dict(payload)
    except JWTError as e:
        raise InvalidTokenError(str(e)) from e


def get_token_expiry(token: str) -> datetime:
    payload = decode_token(token)
    exp = payload.get("exp")
    if exp is None:
        raise InvalidTokenError("Token has no expiry")
    return datetime.fromtimestamp(exp, tz=timezone.utc)


class InvalidTokenError(Exception):
    pass


def _get_secret() -> str:
    secret = (
        os.environ.get("SHADOWFLEET_JWT_SECRET")
        or _load_jwt_secret_from_config()
    )
    if not secret:
        logging.getLogger("shadowfleet.auth").warning(
            "JWT secret not configured — using insecure default. "
            "Set app.jwt_secret in config.yaml or SHADOWFLEET_JWT_SECRET env var."
        )
        secret = "shadowfleet-insecure-dev-secret-change-in-production"
    return secret


def _load_jwt_secret_from_config() -> str | None:
    try:
        raw = load_raw_config()
    except Exception:
        return None
    return raw.get("app", {}).get("jwt_secret") or None
