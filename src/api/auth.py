"""认证接口：登录、登出、获取当前用户。"""

from fastapi import APIRouter, Depends, HTTPException

from src.core.auth import get_current_user
from src.models.schemas import LoginRequest, LoginResponse, UserInfo
from src.services.user_repository import get_user_repository

router = APIRouter(prefix="/auth")


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """用户登录，返回 token 和用户信息。"""
    user_info = get_user_repository().authenticate(request.username, request.password)
    if not user_info:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = user_info.pop("token")
    return LoginResponse(
        token=token,
        user=UserInfo(**user_info),
    )


@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    """登出，清除当前用户 token。"""
    get_user_repository().clear_token(current_user["id"])
    return {"message": "已登出"}


@router.get("/me", response_model=UserInfo)
async def get_me(current_user: dict = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return UserInfo(**current_user)
