"""Runtime-selectable LLM: local (LM Studio) vs frontier (OpenAI).

The Advisor tab switches providers at runtime; the choice persists to
data/llm_config.json and applies to the next consult without a restart.
Chat models are built lazily and cached per (provider, model).
"""
import json
import logging
import threading
from pathlib import Path

from backend.config import settings

logger = logging.getLogger(__name__)

_CONFIG = Path("data/llm_config.json")
_lock = threading.Lock()
_cache: dict = {}


def _load() -> dict:
    try:
        return json.loads(_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def openai_model() -> str:
    return _load().get("openai_model") or settings.openai_model


def custom_model() -> str:
    return _load().get("custom_model") or settings.custom_model or "unset"


def active() -> dict:
    cfg = _load()
    provider = cfg.get("provider") or settings.llm_provider
    if provider == "openai":
        model = openai_model()
    elif provider == "custom":
        model = custom_model()
    elif provider == "none":
        model = "builtin"
    else:
        model = settings.model
    return {"provider": provider, "model": model}


def set_active(provider: str, model: str | None = None) -> dict:
    cfg = _load()
    cfg["provider"] = provider
    if provider == "openai" and model:
        cfg["openai_model"] = model.strip()
    if provider == "custom" and model:
        cfg["custom_model"] = model.strip()
    _CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    logger.info("LLM switched to %s / %s", provider,
                model or active()["model"])
    return active()


def _build(provider: str, model: str):
    if provider == "none":
        raise RuntimeError("deterministic mode has no chat model — callers "
                           "must branch on active()['provider'] first")
    if provider == "custom":
        # any OpenAI-compatible endpoint: Groq, OpenRouter, Together,
        # Gemini's compat layer, a friend's LM Studio over LAN, ...
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, base_url=settings.custom_base_url,
                          api_key=settings.custom_api_key or "unset")
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        # Reasoning models (o-series, gpt-5.x) reject temperature and use
        # max_completion_tokens internally — pass nothing but the model.
        return ChatOpenAI(model=model,
                          api_key=settings.openai_api_key or "unset")
    if provider == "lmstudio":
        # LM Studio speaks the OpenAI API. Start its local server (Developer
        # tab); enable JIT model loading + idle auto-unload.
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, base_url=settings.lmstudio_base_url,
                          api_key="lm-studio", temperature=0.3)
    if provider == "local":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model)
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=model, max_tokens=8000,
                         api_key=settings.anthropic_api_key or "unset")


def get_llm():
    a = active()
    key = (a["provider"], a["model"])
    with _lock:
        if key not in _cache:
            _cache[key] = _build(*key)
        return _cache[key]
