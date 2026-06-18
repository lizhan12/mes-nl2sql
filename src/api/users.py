"""用户管理接口（仅 admin 可访问）。"""

from fastapi import APIRouter, Depends, HTTPException, Query

from src.core.auth import require_admin
from src.models.schemas import PasswordResetRequest, UserCreateRequest, UserInfo, UserListResponse, UserUpdateRequest
from src.services.user_repository import get_user_repository

router = APIRouter(prefix="/api/users")


@router.get("", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=5, le=100, description="每页行数"),
    search: str = Query("", description="按用户名或显示名搜索"),
    _: dict = Depends(require_admin),
):
    """分页查询用户列表。"""
    result = get_user_repository().list_users(page=page, page_size=page_size, search=search)
    return UserListResponse(
        items=[UserInfo(**u) for u in result["items"]],
        total_rows=result["total_rows"],
        page=result["page"],
        page_size=result["page_size"],
        total_pages=result["total_pages"],
    )


@router.post("", response_model=UserInfo)
async def create_user(
    request: UserCreateRequest,
    _: dict = Depends(require_admin),
):
    """创建用户。"""
    existing = get_user_repository().get_user_by_username(request.username)
    if existing:
        raise HTTPException(status_code=409, detail=f"用户名 {request.username} 已存在")
    try:
        user_info = get_user_repository().create_user(
            username=request.username,
            password=request.password,
            display_name=request.display_name,
            role=request.role,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"创建用户失败: {exc}") from exc
    return UserInfo(**user_info)


@router.put("/{user_id}", response_model=UserInfo)
async def update_user(
    user_id: int,
    request: UserUpdateRequest,
    _: dict = Depends(require_admin),
):
    """更新用户显示名和角色。"""
    user_info = get_user_repository().update_user(
        user_id=user_id,
        display_name=request.display_name,
        role=request.role,
    )
    if not user_info:
        raise HTTPException(status_code=404, detail=f"用户 {user_id} 不存在")
    return UserInfo(**user_info)


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    request: PasswordResetRequest,
    _: dict = Depends(require_admin),
):
    """重置用户密码。"""
    user = get_user_repository().get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"用户 {user_id} 不存在")
    get_user_repository().reset_password(user_id, request.new_password)
    return {"message": "密码已重置"}


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    current_user: dict = Depends(require_admin),
):
    """删除用户（禁止删除自己）。"""
    if current_user["id"] == user_id:
        raise HTTPException(status_code=400, detail="不能删除当前登录用户")
    deleted = get_user_repository().delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"用户 {user_id} 不存在")
    return {"message": "用户已删除"}
