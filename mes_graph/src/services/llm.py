"""LLM 客户端封装。"""

from langchain_openai import ChatOpenAI

from src.core.config import settings


def _build_openai_kwargs(model: str, temperature: float = 0.0) -> dict:
    return dict(
        model=model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=max(temperature, 0.01),
        streaming=True,
    )


def get_llm(model: str | None = None, temperature: float = 0.0) -> ChatOpenAI:
    """获取 SQL 生成用 LLM，默认使用强模型。"""
    return ChatOpenAI(**_build_openai_kwargs(model or settings.llm_model, temperature))


def get_intent_llm(temperature: float = 0.0) -> ChatOpenAI:
    """获取意图理解用 LLM，默认使用更便宜的模型。"""
    return ChatOpenAI(**_build_openai_kwargs(settings.intent_model, temperature))
