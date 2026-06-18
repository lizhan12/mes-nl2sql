"""认证与鉴权依赖。

提供 FastAPI 依赖注入函数，用于解析当前登录用户和校验管理员权限。
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from src.services.user_repository import get_user_repository


def get_current_user(authorization: str = Header(default="")) -> dict:
    """从 Authorization: Bearer {token} 解析当前用户。

    Raises:
        HTTPException 401: 未提供 token 或 token 无效。
    """
    token = ""
    if authorization:
        # 兼容 "Bearer xxx" 和直接传 token 两种形式
        parts = authorization.split(" ", 1)
        token = parts[1].strip() if len(parts) == 2 else authorization.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证信息",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_repository().get_user_by_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """要求当前用户为 admin 角色。

    通过 Depends 链式依赖先解析当前用户，再校验角色。
    """
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足，需要管理员权限",
        )
    return user
