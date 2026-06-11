"""请求限流中间件。

基于客户端 IP 的滑动窗口限流。
每个 IP 在每个时间窗口内最多允许 N 次请求。
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.config import settings

logger = logging.getLogger(__name__)

# 限流白名单路径（不限流）
_EXEMPT_PREFIXES = (
    "/health",
    "/docs",
    "/openapi.json",
    "/console",
)

# 每个 IP 的请求时间戳列表
# 格式: {ip: [timestamp, timestamp, ...]}
_window: dict[str, list[float]] = defaultdict(list)


def _clean_expired(ip: str, now: float) -> None:
    """清理时间窗口外的过期记录。"""
    expire_before = now - settings.rate_limit_window_seconds
    records = _window[ip]
    # 二分找到第一个未过期的位置，切掉前面的
    for i, ts in enumerate(records):
        if ts >= expire_before:
            _window[ip] = records[i:]
            return
    _window[ip] = []


def _get_client_ip(request: Request) -> str:
    """获取客户端真实 IP，优先从代理头获取。"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    client = request.client
    return client.host if client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """滑动窗口限流中间件。

    配置 (来自 Settings):
      - rate_limit_enabled: 是否启用限流，默认 True
      - rate_limit_max_requests: 每个窗口内最大请求数，默认 30
      - rate_limit_window_seconds: 时间窗口大小（秒），默认 60
    """

    async def dispatch(self, request: Request, call_next):
        # 未启用限流 → 放行
        if not settings.rate_limit_enabled:
            return await call_next(request)

        # 白名单路径 → 放行
        path = request.url.path
        if path.startswith(_EXEMPT_PREFIXES):
            return await call_next(request)

        # 校验频率
        ip = _get_client_ip(request)
        now = time.time()

        try:
            _clean_expired(ip, now)
            count = len(_window[ip])

            if count >= settings.rate_limit_max_requests:
                logger.warning("rate_limit: IP %s 超过限制 (%d/%ds)", ip, count, settings.rate_limit_window_seconds)
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": f"请求过于频繁，请 {settings.rate_limit_window_seconds} 秒后重试",
                        "retry_after": settings.rate_limit_window_seconds,
                    },
                )

            # 记录本次请求
            _window[ip].append(now)

        except Exception as exc:
            # 限流逻辑异常时放行，避免影响正常请求
            logger.warning("rate_limit: 限流检查异常，放行: %s", exc)

        return await call_next(request)


def _trim_stale_records() -> None:
    """清理所有 IP 的过期记录（避免内存泄漏），可定期调用。"""
    now = time.time()
    stale_threshold = now - settings.rate_limit_window_seconds * 2
    stale_ips = [ip for ip, records in _window.items() if not records or records[-1] < stale_threshold]
    for ip in stale_ips:
        del _window[ip]
    if stale_ips:
        logger.debug("rate_limit: 清理 %d 个过期 IP 记录", len(stale_ips))
