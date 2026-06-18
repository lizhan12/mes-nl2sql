"""LLM 客户端封装。"""

from langchain_openai import ChatOpenAI

from src.core.config import settings


def _build_openai_kwargs(model: str, temperature: float = 0.0, streaming: bool = True) -> dict:
    return {
        "model": model,
        "api_key": settings.openai_api_key,
        "base_url": settings.openai_base_url,
        "temperature": max(temperature, 0.01),
        "streaming": streaming,
        "max_tokens": settings.llm_max_tokens,
        # 关闭 Qwen3 thinking token 生成
        "extra_body": {"enable_thinking": False},
    }


def get_llm(model: str | None = None, temperature: float = 0.0, streaming: bool | None = None) -> ChatOpenAI:
    """获取 SQL 生成用 LLM，默认使用强模型。

    Args:
        model: 模型名，为空则使用 settings.llm_model
        temperature: 温度
        streaming: 是否启用流式输出，为 None 则使用 settings.llm_streaming_enabled
    """
    if streaming is None:
        streaming = settings.llm_streaming_enabled
    return ChatOpenAI(**_build_openai_kwargs(model or settings.llm_model, temperature, streaming))


def get_intent_llm(temperature: float = 0.0, streaming: bool | None = None) -> ChatOpenAI:
    """获取意图理解用 LLM，使用轻量模型 + 小 token 上限。

    Args:
        temperature: 温度
        streaming: 是否启用流式输出，为 None 则使用 settings.llm_streaming_enabled
    """
    if streaming is None:
        streaming = settings.llm_streaming_enabled
    kwargs = _build_openai_kwargs(settings.intent_model, temperature, streaming)
    kwargs["max_tokens"] = settings.intent_max_tokens
    return ChatOpenAI(**kwargs)
