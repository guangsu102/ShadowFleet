from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from api.auth.db import AuthUserRepo
from api.auth.jwt import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from utils.config_parser import load_raw_config
from api.auth.schemas import (
    CurrentUser,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
    UserUpdate,
    UserRole,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

_security = HTTPBearer(auto_error=False)


def _get_secret() -> str:
    import logging
    import os
    secret = os.environ.get("SHADOWFLEET_JWT_SECRET")
    if not secret:
        try:
            raw = load_raw_config()
            secret = raw.get("app", {}).get("jwt_secret")
        except Exception:
            secret = None
    if not secret:
        logging.getLogger("shadowfleet.auth").warning("JWT secret not configured — using insecure default")
        secret = "shadowfleet-insecure-dev-secret-change-in-production"
    return secret


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(credentials.credentials, _get_secret(), algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject")
    user = AuthUserRepo().get_by_id(int(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return CurrentUser(id=user["id"], username=user["username"], role=UserRole(user["role"]))


async def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def _token_response(user_id: int, username: str, role: str) -> TokenResponse:
    access = create_access_token({"sub": str(user_id), "username": username, "role": role})
    refresh = create_refresh_token({"sub": str(user_id)})
    return TokenResponse(access_token=access, refresh_token=refresh, expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60)


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest) -> TokenResponse:
    user = AuthUserRepo().authenticate(request.username, request.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    return _token_response(user["id"], user["username"], user["role"])


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: RefreshRequest) -> TokenResponse:
    try:
        payload = decode_token(request.refresh_token)
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject")
    user = AuthUserRepo().get_by_id(int(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return _token_response(user["id"], user["username"], user["role"])


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser = Depends(get_current_user)) -> UserResponse:
    user = AuthUserRepo().get_by_id(current_user.id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(
        id=user["id"], username=user["username"], role=user["role"],
        is_active=bool(user["is_active"]),
        created_at=datetime.fromisoformat(user["created_at"]),
        updated_at=datetime.fromisoformat(user["updated_at"]) if user["updated_at"] else None,
    )


@router.get("/users", response_model=list[UserResponse])
async def list_users(_: CurrentUser = Depends(require_admin)) -> list[UserResponse]:
    return [
        UserResponse(
            id=u["id"], username=u["username"], role=u["role"], is_active=bool(u["is_active"]),
            created_at=datetime.fromisoformat(u["created_at"]),
            updated_at=datetime.fromisoformat(u["updated_at"]) if u.get("updated_at") else None,
        )
        for u in AuthUserRepo().list_users()
    ]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(request: UserCreate, _: CurrentUser = Depends(require_admin)) -> UserResponse:
    user_id = AuthUserRepo().create_user(request.username, request.password, request.role.value)
    user = AuthUserRepo().get_by_id(user_id)
    return UserResponse(
        id=user["id"], username=user["username"], role=user["role"],
        is_active=bool(user["is_active"]),
        created_at=datetime.fromisoformat(user["created_at"]), updated_at=None,
    )


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(user_id: int, request: UserUpdate, _: CurrentUser = Depends(require_admin)) -> UserResponse:
    user = AuthUserRepo().update_user(user_id, role=request.role.value if request.role else None, password=request.password)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(
        id=user["id"], username=user["username"], role=user["role"], is_active=bool(user["is_active"]),
        created_at=datetime.fromisoformat(user["created_at"]),
        updated_at=datetime.fromisoformat(user["updated_at"]) if user.get("updated_at") else None,
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, _: CurrentUser = Depends(require_admin)) -> None:
    if not AuthUserRepo().delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")
