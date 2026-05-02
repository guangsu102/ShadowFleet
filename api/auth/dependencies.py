from __future__ import annotations

from fastapi import Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from api.auth.jwt import ALGORITHM as _ALGORITHM
from api.auth.jwt import _get_secret as _jwt_secret_loader
from api.auth.schemas import CurrentUser, UserRole

_security = HTTPBearer(auto_error=False)


async def get_current_user(request: Request) -> CurrentUser:
    credentials: HTTPAuthorizationCredentials | None = await _security(request)
    if credentials is None:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(credentials.credentials, _jwt_secret_loader(), algorithms=[_ALGORITHM])
    except JWTError:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if payload.get("type") != "access":
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user_id = payload.get("sub")
    if user_id is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject")

    from api.auth.db import AuthUserRepo
    user = AuthUserRepo().get_by_id(int(user_id))
    if user is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return CurrentUser(id=user["id"], username=user["username"], role=UserRole(user["role"]))


async def require_admin(request: Request) -> CurrentUser:
    user = await get_current_user(request)
    if user.role.value != "admin":
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


async def require_operator(request: Request) -> CurrentUser:
    user = await get_current_user(request)
    if user.role.value not in ("admin", "operator"):
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator or admin access required")
    return user
