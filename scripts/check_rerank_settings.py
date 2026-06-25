"""检查 settings 实际加载的值。"""

from src.core.config import settings

print(f"rerank_base_url   = {settings.rerank_base_url!r}")
print(f"rerank_model      = {settings.rerank_model!r}")
print(f"rerank_provider   = {settings.rerank_provider!r}")
print(f"rerank_mode       = {settings.rerank_mode!r}")
print(f"rerank_key (mask) = {settings.rerank_key[:10] + '...' if settings.rerank_key else '(empty)'}")
