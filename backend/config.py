from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from project_layout import ProjectLayout

_LOGGER = logging.getLogger(__name__)
_RUNTIME_CONFIG_WARNING_KEYS: set[tuple[str, str]] = set()

LLM_PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "display_name": "DeepSeek",
        "model": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com",
        "adapter": "deepseek_langchain",
        "credential_envs": (
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_WRITING_API_KEY",
            "DEEPSEEK_REVIEW_API_KEY",
            "DEEPSEEK_MEMORY_API_KEY",
            "LLM_API_KEY",
        ),
        "model_presets": ("deepseek-v4-pro", "deepseek-v4-flash"),
        "capability_tags": ("long_output", "reasoning", "openai_compatible", "tool_calling"),
        "recommended": True,
    },
    "openai": {
        "display_name": "OpenAI",
        "model": "gpt-4.1-mini",
        "base_url": "https://api.openai.com/v1",
        "adapter": "openai_compatible",
        "credential_envs": ("OPENAI_API_KEY", "LLM_API_KEY"),
        "model_presets": ("gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"),
        "capability_tags": ("reasoning", "openai_compatible", "tool_calling"),
    },
    "openrouter": {
        "display_name": "OpenRouter",
        "model": "openai/gpt-4.1-mini",
        "base_url": "https://openrouter.ai/api/v1",
        "adapter": "openai_compatible",
        "credential_envs": ("OPENROUTER_API_KEY", "LLM_API_KEY"),
        "model_presets": ("openai/gpt-4.1-mini", "anthropic/claude-sonnet-4", "google/gemini-2.5-pro"),
        "capability_tags": ("model_gateway", "openai_compatible"),
    },
    "anthropic": {
        "display_name": "Anthropic",
        "model": "claude-sonnet-4",
        "base_url": "https://api.anthropic.com/v1",
        "adapter": "openai_compatible",
        "credential_envs": ("ANTHROPIC_API_KEY", "LLM_API_KEY"),
        "model_presets": ("claude-sonnet-4", "claude-opus-4", "claude-haiku-3.5"),
        "capability_tags": ("reasoning", "long_context"),
        "metadata": {"native_adapter_pending": True},
    },
    "google": {
        "display_name": "Google Gemini",
        "model": "gemini-2.5-pro",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "adapter": "openai_compatible",
        "credential_envs": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "LLM_API_KEY"),
        "model_presets": ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-1.5-pro"),
        "capability_tags": ("reasoning", "long_context", "openai_compatible"),
    },
    "bailian": {
        "display_name": "阿里百炼 / Qwen",
        "model": "qwen3.5-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "adapter": "openai_compatible",
        "credential_envs": ("BAILIAN_API_KEY", "DASHSCOPE_API_KEY", "LLM_API_KEY"),
        "model_presets": ("qwen3.5-plus", "qwen-plus", "qwen-max", "qwen-turbo"),
        "capability_tags": ("openai_compatible", "tool_calling"),
    },
    "zhipu": {
        "display_name": "智谱 GLM",
        "model": "glm-5",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/",
        "adapter": "openai_compatible",
        "credential_envs": ("ZHIPU_API_KEY", "ZHIPUAI_API_KEY", "LLM_API_KEY"),
        "model_presets": ("glm-5", "glm-4-plus", "glm-4-flash"),
        "capability_tags": ("openai_compatible", "tool_calling"),
    },
    "moonshot": {
        "display_name": "Moonshot / Kimi",
        "model": "kimi-k2",
        "base_url": "https://api.moonshot.cn/v1",
        "adapter": "openai_compatible",
        "credential_envs": ("MOONSHOT_API_KEY", "KIMI_API_KEY", "LLM_API_KEY"),
        "model_presets": ("kimi-k2", "moonshot-v1-128k", "moonshot-v1-32k"),
        "capability_tags": ("long_context", "openai_compatible"),
    },
    "groq": {
        "display_name": "Groq",
        "model": "llama-3.3-70b-versatile",
        "base_url": "https://api.groq.com/openai/v1",
        "adapter": "openai_compatible",
        "credential_envs": ("GROQ_API_KEY", "LLM_API_KEY"),
        "model_presets": ("llama-3.3-70b-versatile", "llama-3.1-8b-instant"),
        "capability_tags": ("fast", "openai_compatible"),
    },
    "xai": {
        "display_name": "xAI",
        "model": "grok-3",
        "base_url": "https://api.x.ai/v1",
        "adapter": "openai_compatible",
        "credential_envs": ("XAI_API_KEY", "LLM_API_KEY"),
        "model_presets": ("grok-3", "grok-3-mini"),
        "capability_tags": ("reasoning", "openai_compatible"),
    },
    "ollama": {
        "display_name": "Ollama Local",
        "model": "llama3.1",
        "base_url": "http://localhost:11434/v1",
        "adapter": "openai_compatible",
        "credential_envs": ("OLLAMA_API_KEY",),
        "model_presets": ("llama3.1", "qwen2.5", "deepseek-r1"),
        "capability_tags": ("local", "openai_compatible"),
        "metadata": {"local_provider": True},
    },
}

EMBEDDING_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "bailian": {
        "model": "text-embedding-v4",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "openai": {
        "model": "text-embedding-3-small",
        "base_url": "https://api.openai.com/v1",
    },
}

PROVIDER_ALIASES = {
    "glm": "zhipu",
    "zhipuai": "zhipu",
    "bigmodel": "zhipu",
    "aliyun": "bailian",
    "dashscope": "bailian",
    "qwen": "bailian",
    "openai-compatible": "openai",
    "compatible": "openai",
    "openrouter.ai": "openrouter",
    "claude": "anthropic",
    "anthropic-openai-compatible": "anthropic",
    "gemini": "google",
    "google-gemini": "google",
    "kimi": "moonshot",
    "moonshot-ai": "moonshot",
    "grok": "xai",
    "x.ai": "xai",
}


@dataclass(frozen=True)
class Settings:
    backend_dir: Path
    project_root: Path
    llm_provider: str
    llm_model: str
    llm_api_key: str | None
    llm_base_url: str
    llm_fallback_provider: str | None
    llm_fallback_model: str | None
    llm_fallback_api_key: str | None
    llm_fallback_base_url: str | None
    llm_timeout_seconds: float
    llm_max_retries: int
    llm_max_output_tokens: int
    llm_long_output_timeout_seconds: float
    llm_thinking_mode: str
    llm_reasoning_effort: str
    embedding_provider: str
    embedding_model: str
    embedding_api_key: str | None
    embedding_base_url: str
    embedding_dimensions: int | None
    vector_store_backend: str
    document_conversion_backend: str
    retrieval_core_backend: str
    qdrant_url: str | None
    qdrant_api_key: str | None
    qdrant_collection_prefix: str
    qdrant_build_batch_size: int
    indexes_root: Path
    document_cache_root: Path
    docling_enabled: bool
    docling_prefer_ocr: bool
    rerank_enabled: bool
    rerank_provider: str
    rerank_model: str | None
    rerank_api_key: str | None
    rerank_base_url: str | None
    rerank_top_n: int
    rerank_candidate_pool: int
    rerank_batch_size: int
    rerank_max_length: int
    rerank_device: str | None
    mineru_api_enabled: bool
    mineru_api_mode: str
    mineru_api_base_url: str | None
    mineru_api_parse_path: str
    mineru_api_key: str | None
    mineru_api_timeout_seconds: int
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 60
    component_char_limit: int = 20_000
    terminal_timeout_seconds: int = 30


def _normalize_runtime_permission_mode(mode: Any) -> str:
    normalized = str(mode or "default").strip().lower()
    if normalized in {"default", "plan", "accept_edits", "bypass", "full_access"}:
        return normalized
    return "default"


def _load_env_file() -> Path:
    backend_dir = Path(__file__).resolve().parent
    load_dotenv(backend_dir / ".env")
    return backend_dir


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


LLM_PROVIDER_MODEL_ENVS: dict[str, str] = {
    "openai": "OPENAI_MODEL",
    "openrouter": "OPENROUTER_MODEL",
    "anthropic": "ANTHROPIC_MODEL",
    "google": "GEMINI_MODEL",
    "moonshot": "MOONSHOT_MODEL",
    "groq": "GROQ_MODEL",
    "xai": "XAI_MODEL",
    "ollama": "OLLAMA_MODEL",
    "zhipu": "ZHIPU_MODEL",
    "bailian": "BAILIAN_MODEL",
    "deepseek": "DEEPSEEK_MODEL",
}

LLM_PROVIDER_BASE_URL_ENVS: dict[str, str] = {
    "openai": "OPENAI_BASE_URL",
    "openrouter": "OPENROUTER_BASE_URL",
    "anthropic": "ANTHROPIC_BASE_URL",
    "google": "GEMINI_BASE_URL",
    "moonshot": "MOONSHOT_BASE_URL",
    "groq": "GROQ_BASE_URL",
    "xai": "XAI_BASE_URL",
    "ollama": "OLLAMA_BASE_URL",
    "zhipu": "ZHIPU_BASE_URL",
    "bailian": "BAILIAN_BASE_URL",
    "deepseek": "DEEPSEEK_BASE_URL",
}


def _provider_specific_env(provider: str | None, env_map: dict[str, str]) -> str | None:
    if not provider:
        return None
    env_name = env_map.get(provider)
    return _first_env(env_name) if env_name else None


def _unique_env_names(names: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        normalized = str(name or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return tuple(unique)


def _provider_credential_envs(provider: str, *, fallback: bool = False) -> tuple[str, ...]:
    defaults = LLM_PROVIDER_DEFAULTS.get(provider) or {}
    names = _unique_env_names(tuple(str(name) for name in defaults.get("credential_envs") or ()))
    if not fallback:
        return names
    provider_names = tuple(name for name in names if name != "LLM_API_KEY")
    if provider == "ollama":
        return provider_names
    return _unique_env_names(("LLM_FALLBACK_API_KEY", *provider_names))


def _provider_config_value(
    provider: str,
    env_map: dict[str, str],
    generic_env: str,
    default_key: str,
) -> str:
    provider_value = _provider_specific_env(provider, env_map)
    if provider_value:
        return provider_value
    generic_value = _first_env(generic_env)
    if generic_value:
        return generic_value
    return str(LLM_PROVIDER_DEFAULTS[provider][default_key])


def _normalize_llm_model_id(provider: str, model: str) -> str:
    normalized = str(model or "").strip()
    if provider == "deepseek":
        return normalized.lower()
    return normalized


def _normalize_provider(
    value: str | None,
    *,
    default: str,
    defaults: dict[str, dict[str, str]],
) -> str:
    normalized = (value or default).strip().lower()
    normalized = PROVIDER_ALIASES.get(normalized, normalized)
    if normalized in defaults:
        return normalized
    return default


def _provider_hint_from_model_base_url(model: str | None, base_url: str | None) -> str:
    haystack = f"{model or ''} {base_url or ''}".strip().lower()
    if not haystack:
        return ""
    if "deepseek" in haystack or "api.deepseek.com" in haystack:
        return "deepseek"
    if "openrouter" in haystack:
        return "openrouter"
    if "anthropic" in haystack or "claude" in haystack:
        return "anthropic"
    if "generativelanguage.googleapis.com" in haystack or "gemini" in haystack:
        return "google"
    if "moonshot" in haystack or "kimi" in haystack:
        return "moonshot"
    if "api.groq.com" in haystack or "groq" in haystack:
        return "groq"
    if "api.x.ai" in haystack or "grok" in haystack:
        return "xai"
    if "localhost:11434" in haystack or "ollama" in haystack:
        return "ollama"
    if "dashscope" in haystack or "aliyuncs.com" in haystack or "qwen" in haystack:
        return "bailian"
    if "bigmodel" in haystack or "zhipu" in haystack or "glm-" in haystack:
        return "zhipu"
    if "api.openai.com" in haystack or haystack.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    return ""


def _normalize_provider_with_payload_hints(provider: str | None, model: str | None, base_url: str | None) -> str | None:
    normalized = _normalize_provider(provider, default="", defaults=LLM_PROVIDER_DEFAULTS)
    hint = _provider_hint_from_model_base_url(model, base_url)
    if hint and normalized and hint != normalized:
        return hint
    return normalized or hint or None


def _resolve_llm_api_key(provider: str) -> str | None:
    runtime_override = _runtime_llm_override()
    override_api_key = str(runtime_override.get("api_key") or "").strip()
    if override_api_key:
        return override_api_key
    return _first_env(*_provider_credential_envs(provider))


def _resolve_llm_model(provider: str) -> str:
    runtime_override = _runtime_llm_override()
    override_model = str(runtime_override.get("model") or "").strip()
    if override_model:
        return _normalize_llm_model_id(provider, override_model)
    model = _provider_config_value(provider, LLM_PROVIDER_MODEL_ENVS, "LLM_MODEL", "model")
    return _normalize_llm_model_id(provider, model)


def _resolve_llm_base_url(provider: str) -> str:
    runtime_override = _runtime_llm_override()
    override_base_url = str(runtime_override.get("base_url") or "").strip()
    if override_base_url:
        return override_base_url
    return _provider_config_value(provider, LLM_PROVIDER_BASE_URL_ENVS, "LLM_BASE_URL", "base_url")


def _resolve_llm_fallback_provider() -> str | None:
    runtime_override = _runtime_llm_override()
    if "fallback_provider" in runtime_override:
        value = str(runtime_override.get("fallback_provider") or "").strip().lower()
        if value in {"", "none", "disabled", "off"}:
            return None
        return _normalize_provider_with_payload_hints(
            value,
            str(runtime_override.get("fallback_model") or ""),
            str(runtime_override.get("fallback_base_url") or ""),
        )
    value = _first_env("LLM_FALLBACK_PROVIDER")
    if not value:
        return None
    if str(value or "").strip().lower() in {"", "none", "disabled", "off"}:
        return None
    declared_provider = _normalize_provider(value, default="", defaults=LLM_PROVIDER_DEFAULTS)
    provider_model = _provider_specific_env(declared_provider, LLM_PROVIDER_MODEL_ENVS)
    provider_base_url = _provider_specific_env(declared_provider, LLM_PROVIDER_BASE_URL_ENVS)
    fallback_model = _first_env("LLM_FALLBACK_MODEL") or ""
    fallback_base_url = _first_env("LLM_FALLBACK_BASE_URL") or ""
    if provider_model:
        normalized = _normalize_provider_with_payload_hints(
            declared_provider,
            provider_model,
            provider_base_url or fallback_base_url,
        )
        return normalized or None
    if fallback_model or fallback_base_url:
        normalized = _normalize_provider_with_payload_hints(
            declared_provider or value,
            fallback_model,
            fallback_base_url,
        )
        return normalized or None
    normalized = _normalize_provider_with_payload_hints(
        declared_provider or value,
        "",
        provider_base_url or "",
    )
    return normalized or None


def _runtime_config_path() -> Path:
    return Path(__file__).resolve().parent / "config.json"


def _warn_runtime_config_issue(path: Path, reason: str, detail: str) -> None:
    key = (str(path), reason)
    if key in _RUNTIME_CONFIG_WARNING_KEYS:
        return
    _RUNTIME_CONFIG_WARNING_KEYS.add(key)
    _LOGGER.warning("Ignoring runtime config at %s: %s", path, detail)


def _runtime_payload() -> dict[str, Any]:
    path = _runtime_config_path()
    try:
        raw_payload = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        _warn_runtime_config_issue(path, "read_error", f"{exc.__class__.__name__}: {exc}")
        return {}
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        _warn_runtime_config_issue(path, "json_decode_error", f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")
        return {}
    if not isinstance(payload, dict):
        _warn_runtime_config_issue(path, "non_object_payload", f"expected a JSON object, got {type(payload).__name__}")
        return {}
    return payload


def _runtime_llm_override() -> dict[str, Any]:
    payload = _runtime_payload()
    model_config = payload.get("model_provider")
    return dict(model_config) if isinstance(model_config, dict) else {}


def _runtime_system_section(section: str) -> dict[str, Any]:
    payload = _runtime_payload()
    system_config = payload.get("system_config")
    if not isinstance(system_config, dict):
        return {}
    section_config = system_config.get(section)
    return dict(section_config) if isinstance(section_config, dict) else {}


def _runtime_system_value(section: str, key: str) -> Any:
    return _runtime_system_section(section).get(key)


def _resolve_llm_fallback_api_key(provider: str | None) -> str | None:
    if not provider:
        return None
    runtime_override = _runtime_llm_override()
    override_api_key = str(runtime_override.get("fallback_api_key") or "").strip()
    if override_api_key:
        return override_api_key
    return _first_env(*_provider_credential_envs(provider, fallback=True))


def _resolve_llm_fallback_value(
    provider: str,
    env_map: dict[str, str],
    fallback_env: str,
    default_key: str,
) -> str:
    declared_provider = _normalize_provider(_first_env("LLM_FALLBACK_PROVIDER"), default="", defaults=LLM_PROVIDER_DEFAULTS)
    provider_value = _provider_specific_env(provider, env_map)
    if declared_provider == provider and provider_value:
        return provider_value
    fallback_value = _first_env(fallback_env)
    if fallback_value:
        return fallback_value
    return provider_value or str(LLM_PROVIDER_DEFAULTS[provider][default_key])


def _resolve_llm_fallback_model(provider: str | None) -> str | None:
    if not provider:
        return None
    runtime_override = _runtime_llm_override()
    override_model = str(runtime_override.get("fallback_model") or "").strip()
    if override_model:
        return _normalize_llm_model_id(provider, override_model)
    model = _resolve_llm_fallback_value(provider, LLM_PROVIDER_MODEL_ENVS, "LLM_FALLBACK_MODEL", "model")
    return _normalize_llm_model_id(provider, model)


def _resolve_llm_fallback_base_url(provider: str | None) -> str | None:
    if not provider:
        return None
    runtime_override = _runtime_llm_override()
    override_base_url = str(runtime_override.get("fallback_base_url") or "").strip()
    if override_base_url:
        return override_base_url
    return _resolve_llm_fallback_value(provider, LLM_PROVIDER_BASE_URL_ENVS, "LLM_FALLBACK_BASE_URL", "base_url")


def _resolve_llm_thinking_mode() -> str:
    value = str(_runtime_system_value("runtime", "llm_thinking_mode") or os.getenv("LLM_THINKING_MODE") or "disabled").strip().lower()
    if value in {"on", "true", "1", "enabled", "enable"}:
        return "enabled"
    if value in {"off", "false", "0", "disabled", "disable"}:
        return "disabled"
    return "disabled"


def _resolve_llm_reasoning_effort() -> str:
    value = str(_runtime_system_value("runtime", "llm_reasoning_effort") or os.getenv("LLM_REASONING_EFFORT") or "auto").strip().lower()
    if value in {"", "auto", "default", "adaptive"}:
        return "auto"
    if value in {"max", "xhigh"}:
        return "max"
    return "high"


def _resolve_embedding_api_key(provider: str) -> str | None:
    override_api_key = str(_runtime_system_value("embedding", "api_key") or "").strip()
    if override_api_key:
        return override_api_key
    if provider == "bailian":
        return _first_env("EMBEDDING_API_KEY", "BAILIAN_API_KEY", "DASHSCOPE_API_KEY")
    return _first_env("EMBEDDING_API_KEY", "OPENAI_API_KEY")


def _resolve_embedding_model(provider: str) -> str:
    override_model = str(_runtime_system_value("embedding", "model") or "").strip()
    if override_model:
        return override_model
    return _first_env("EMBEDDING_MODEL") or EMBEDDING_PROVIDER_DEFAULTS[provider]["model"]


def _resolve_embedding_base_url(provider: str) -> str:
    override_base_url = str(_runtime_system_value("embedding", "base_url") or "").strip()
    if override_base_url:
        return override_base_url
    if provider == "bailian":
        return (
            _first_env("EMBEDDING_BASE_URL", "BAILIAN_BASE_URL")
            or EMBEDDING_PROVIDER_DEFAULTS[provider]["base_url"]
        )
    return (
        _first_env("EMBEDDING_BASE_URL", "OPENAI_BASE_URL")
        or EMBEDDING_PROVIDER_DEFAULTS[provider]["base_url"]
    )


def _resolve_embedding_dimensions() -> int | None:
    override = _runtime_system_value("embedding", "dimensions")
    if override not in {None, ""}:
        try:
            value = int(override)
        except (TypeError, ValueError):
            value = 1024
        return value if value > 0 else 1024
    raw = _first_env("EMBEDDING_DIMENSIONS")
    if not raw:
        return 1024
    try:
        value = int(raw)
    except ValueError:
        return 1024
    return value if value > 0 else 1024


def _resolve_vector_store_backend() -> str:
    override = str(_runtime_system_value("retrieval", "vector_store_backend") or "").strip().lower()
    if override == "qdrant":
        return override
    value = (_first_env("VECTOR_STORE_BACKEND") or "qdrant").strip().lower()
    if value == "qdrant":
        return value
    return "qdrant"


def _resolve_document_conversion_backend() -> str:
    override = str(_runtime_system_value("document", "document_conversion_backend") or "").strip().lower()
    if override == "docling":
        return override
    value = (_first_env("DOCUMENT_CONVERSION_BACKEND") or "docling").strip().lower()
    if value == "docling":
        return value
    return "docling"


def _resolve_retrieval_core_backend() -> str:
    override = str(_runtime_system_value("retrieval", "retrieval_core_backend") or "").strip().lower()
    if override == "llamaindex":
        return override
    value = (_first_env("RETRIEVAL_CORE_BACKEND") or "llamaindex").strip().lower()
    if value == "llamaindex":
        return value
    return "llamaindex"


def _resolve_qdrant_url() -> str | None:
    override = str(_runtime_system_value("retrieval", "qdrant_url") or "").strip()
    if override:
        return override
    value = _first_env("QDRANT_URL", "QDRANT_HOST")
    return value or None


def _resolve_qdrant_api_key() -> str | None:
    override = str(_runtime_system_value("retrieval", "qdrant_api_key") or "").strip()
    if override:
        return override
    value = _first_env("QDRANT_API_KEY")
    return value or None


def _resolve_qdrant_collection_prefix() -> str:
    override = str(_runtime_system_value("retrieval", "qdrant_collection_prefix") or "").strip()
    if override:
        return override
    value = (_first_env("QDRANT_COLLECTION_PREFIX") or "agent").strip()
    return value or "agent"


def _resolve_qdrant_build_batch_size() -> int:
    override = _runtime_system_value("retrieval", "qdrant_build_batch_size")
    return _resolve_positive_int("QDRANT_BUILD_BATCH_SIZE", 128, override)


def _resolve_positive_int(name: str, default: int, override: Any = None) -> int:
    raw = override if override not in {None, ""} else _first_env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _resolve_nonnegative_int(name: str, default: int, override: Any = None) -> int:
    raw = override if override not in {None, ""} else _first_env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def _resolve_positive_float(name: str, default: float, override: Any = None) -> float:
    raw = override if override not in {None, ""} else _first_env(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _resolve_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _resolve_docling_enabled() -> bool:
    override = _runtime_system_value("document", "docling_enabled")
    if override not in {None, ""}:
        return _resolve_bool(str(override), default=True)
    return _resolve_bool(os.getenv("DOCLING_ENABLED"), default=True)


def _resolve_docling_prefer_ocr() -> bool:
    override = _runtime_system_value("document", "docling_prefer_ocr")
    if override not in {None, ""}:
        return _resolve_bool(str(override), default=False)
    return _resolve_bool(os.getenv("DOCLING_PREFER_OCR"), default=False)


def _resolve_rerank_provider() -> str:
    override = str(_runtime_system_value("retrieval", "rerank_provider") or "").strip().lower()
    if override:
        return override
    return (_first_env("RERANK_PROVIDER") or "heuristic").strip().lower()


def _resolve_rerank_model() -> str | None:
    override = str(_runtime_system_value("retrieval", "rerank_model") or "").strip()
    if override:
        return override
    value = _first_env("RERANK_MODEL")
    return value or None


def _resolve_rerank_api_key() -> str | None:
    override = str(_runtime_system_value("retrieval", "rerank_api_key") or "").strip()
    if override:
        return override
    value = _first_env("RERANK_API_KEY")
    return value or None


def _resolve_rerank_base_url() -> str | None:
    override = str(_runtime_system_value("retrieval", "rerank_base_url") or "").strip()
    if override:
        return override
    value = _first_env("RERANK_BASE_URL")
    return value or None


def _resolve_rerank_top_n() -> int:
    override = _runtime_system_value("retrieval", "rerank_top_n")
    if override not in {None, ""}:
        return _resolve_positive_int("RERANK_TOP_N", 50, override)
    raw = _first_env("RERANK_TOP_N")
    if not raw:
        return 50
    try:
        value = int(raw)
    except ValueError:
        return 50
    return value if value > 0 else 50


def _resolve_rerank_candidate_pool() -> int:
    override = _runtime_system_value("retrieval", "rerank_candidate_pool")
    if override not in {None, ""}:
        return _resolve_positive_int("RERANK_CANDIDATE_POOL", 200, override)
    raw = _first_env("RERANK_CANDIDATE_POOL")
    if not raw:
        return 200
    try:
        value = int(raw)
    except ValueError:
        return 200
    return value if value > 0 else 200


def _resolve_rerank_batch_size() -> int:
    override = _runtime_system_value("retrieval", "rerank_batch_size")
    if override not in {None, ""}:
        return _resolve_positive_int("RERANK_BATCH_SIZE", 8, override)
    raw = _first_env("RERANK_BATCH_SIZE")
    if not raw:
        return 8
    try:
        value = int(raw)
    except ValueError:
        return 8
    return value if value > 0 else 8


def _resolve_rerank_max_length() -> int:
    override = _runtime_system_value("retrieval", "rerank_max_length")
    if override not in {None, ""}:
        return _resolve_positive_int("RERANK_MAX_LENGTH", 512, override)
    raw = _first_env("RERANK_MAX_LENGTH")
    if not raw:
        return 512
    try:
        value = int(raw)
    except ValueError:
        return 512
    return value if value > 0 else 512


def _resolve_rerank_device() -> str | None:
    override = str(_runtime_system_value("retrieval", "rerank_device") or "").strip()
    if override:
        return override
    value = _first_env("RERANK_DEVICE")
    return value or None


def _resolve_mineru_api_base_url() -> str | None:
    override = str(_runtime_system_value("document", "mineru_api_base_url") or "").strip()
    if override:
        return override
    value = _first_env("MINERU_API_BASE_URL", "MINERU_BASE_URL")
    return value or None


def _resolve_mineru_api_mode() -> str:
    override = str(_runtime_system_value("document", "mineru_api_mode") or "").strip().lower()
    if override in {"local_sync", "cloud_v4_batch"}:
        return override
    explicit = (_first_env("MINERU_API_MODE") or "").strip().lower()
    if explicit in {"local_sync", "cloud_v4_batch"}:
        return explicit

    base_url = (_resolve_mineru_api_base_url() or "").lower()
    parse_path = (_first_env("MINERU_API_PARSE_PATH", "MINERU_PARSE_PATH") or "").lower()
    if "mineru.net" in base_url or "/api/v4/" in base_url or "/api/v4/" in parse_path:
        return "cloud_v4_batch"
    return "local_sync"


def _resolve_mineru_api_parse_path() -> str:
    default = "/api/v4/file-urls/batch" if _resolve_mineru_api_mode() == "cloud_v4_batch" else "/file_parse"
    override = str(_runtime_system_value("document", "mineru_api_parse_path") or "").strip()
    value = override or _first_env("MINERU_API_PARSE_PATH", "MINERU_PARSE_PATH") or default
    normalized = value.strip()
    if not normalized:
        return default
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return normalized
    if not normalized.startswith("/"):
        return "/" + normalized
    return normalized


def _resolve_mineru_api_key() -> str | None:
    override = str(_runtime_system_value("document", "mineru_api_key") or "").strip()
    if override:
        return override
    value = _first_env("MINERU_API_KEY", "MINERU_API_TOKEN")
    return value or None


def _resolve_mineru_api_timeout_seconds() -> int:
    return _resolve_positive_int("MINERU_API_TIMEOUT_SECONDS", 180, _runtime_system_value("document", "mineru_api_timeout_seconds"))


def _resolve_mineru_api_enabled() -> bool:
    override = _runtime_system_value("document", "mineru_api_enabled")
    enabled = _resolve_bool(str(override), default=False) if override not in {None, ""} else _resolve_bool(os.getenv("MINERU_API_ENABLED"), default=False)
    if not enabled:
        return False
    return bool(_resolve_mineru_api_base_url())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    backend_dir = _load_env_file()
    project_root = backend_dir.parent
    layout = ProjectLayout.from_backend_dir(backend_dir)
    runtime_llm = _runtime_llm_override()

    llm_provider = _normalize_provider(
        str(runtime_llm.get("provider") or "").strip() or os.getenv("LLM_PROVIDER"),
        default="deepseek",
        defaults=LLM_PROVIDER_DEFAULTS,
    )
    embedding_provider = _normalize_provider(
        str(_runtime_system_value("embedding", "provider") or "").strip() or os.getenv("EMBEDDING_PROVIDER"),
        default="bailian",
        defaults=EMBEDDING_PROVIDER_DEFAULTS,
    )
    llm_fallback_provider = _resolve_llm_fallback_provider()

    return Settings(
        backend_dir=backend_dir,
        project_root=project_root,
        llm_provider=llm_provider,
        llm_model=_resolve_llm_model(llm_provider),
        llm_api_key=_resolve_llm_api_key(llm_provider),
        llm_base_url=_resolve_llm_base_url(llm_provider),
        llm_fallback_provider=llm_fallback_provider,
        llm_fallback_model=_resolve_llm_fallback_model(llm_fallback_provider),
        llm_fallback_api_key=_resolve_llm_fallback_api_key(llm_fallback_provider),
        llm_fallback_base_url=_resolve_llm_fallback_base_url(llm_fallback_provider),
        llm_timeout_seconds=_resolve_positive_float("LLM_TIMEOUT_SECONDS", 45.0, _runtime_system_value("runtime", "llm_timeout_seconds")),
        llm_max_retries=_resolve_nonnegative_int("LLM_MAX_RETRIES", 2, _runtime_system_value("runtime", "llm_max_retries")),
        llm_max_output_tokens=_resolve_positive_int("LLM_MAX_OUTPUT_TOKENS", 65536, _runtime_system_value("runtime", "llm_max_output_tokens")),
        llm_long_output_timeout_seconds=_resolve_positive_float("LLM_LONG_OUTPUT_TIMEOUT_SECONDS", 180.0, _runtime_system_value("runtime", "llm_long_output_timeout_seconds")),
        llm_thinking_mode=_resolve_llm_thinking_mode(),
        llm_reasoning_effort=_resolve_llm_reasoning_effort(),
        embedding_provider=embedding_provider,
        embedding_model=_resolve_embedding_model(embedding_provider),
        embedding_api_key=_resolve_embedding_api_key(embedding_provider),
        embedding_base_url=_resolve_embedding_base_url(embedding_provider),
        embedding_dimensions=_resolve_embedding_dimensions(),
        vector_store_backend=_resolve_vector_store_backend(),
        document_conversion_backend=_resolve_document_conversion_backend(),
        retrieval_core_backend=_resolve_retrieval_core_backend(),
        qdrant_url=_resolve_qdrant_url(),
        qdrant_api_key=_resolve_qdrant_api_key(),
        qdrant_collection_prefix=_resolve_qdrant_collection_prefix(),
        qdrant_build_batch_size=_resolve_qdrant_build_batch_size(),
        indexes_root=layout.indexes_dir,
        document_cache_root=layout.document_cache_dir,
        docling_enabled=_resolve_docling_enabled(),
        docling_prefer_ocr=_resolve_docling_prefer_ocr(),
        rerank_enabled=(
            _resolve_bool(str(_runtime_system_value("retrieval", "rerank_enabled")), default=False)
            if _runtime_system_value("retrieval", "rerank_enabled") not in {None, ""}
            else _resolve_bool(os.getenv("RERANK_ENABLED"), default=False)
        ),
        rerank_provider=_resolve_rerank_provider(),
        rerank_model=_resolve_rerank_model(),
        rerank_api_key=_resolve_rerank_api_key(),
        rerank_base_url=_resolve_rerank_base_url(),
        rerank_top_n=_resolve_rerank_top_n(),
        rerank_candidate_pool=_resolve_rerank_candidate_pool(),
        rerank_batch_size=_resolve_rerank_batch_size(),
        rerank_max_length=_resolve_rerank_max_length(),
        rerank_device=_resolve_rerank_device(),
        mineru_api_enabled=_resolve_mineru_api_enabled(),
        mineru_api_mode=_resolve_mineru_api_mode(),
        mineru_api_base_url=_resolve_mineru_api_base_url(),
        mineru_api_parse_path=_resolve_mineru_api_parse_path(),
        mineru_api_key=_resolve_mineru_api_key(),
        mineru_api_timeout_seconds=_resolve_mineru_api_timeout_seconds(),
        component_char_limit=_resolve_positive_int("COMPONENT_CHAR_LIMIT", 20_000, _runtime_system_value("runtime", "component_char_limit")),
        terminal_timeout_seconds=_resolve_positive_int("TERMINAL_TIMEOUT_SECONDS", 30, _runtime_system_value("runtime", "terminal_timeout_seconds")),
    )


class RuntimeConfigManager:
    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path
        self._lock = threading.RLock()
        self._default_config = {
            "rag_mode": False,
            "permission_mode": "default",
            "orchestration_plan_mode": "primary",
            "context_budget_preset": "deepseek_1m",
            "code_environment": {
                "enabled": True,
                "workspace_root_policy": "project_root",
                "pi_sidecar": {
                    "enabled": False,
                    "mode": "diagnostic_only",
                    "pi_source_root": "D:/AI应用/pi-main",
                    "pi_cli_path": "",
                },
            },
        }

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self._config_path.exists():
                self.save(self._default_config)
            try:
                loaded = json.loads(self._config_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                _warn_runtime_config_issue(
                    self._config_path,
                    "runtime_manager_json_decode_error",
                    f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}",
                )
                self.save(self._default_config)
                return dict(self._default_config)
            if not isinstance(loaded, dict):
                _warn_runtime_config_issue(
                    self._config_path,
                    "runtime_manager_non_object_payload",
                    f"expected a JSON object, got {type(loaded).__name__}",
                )
                self.save(self._default_config)
                return dict(self._default_config)
            return loaded

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        merged = dict(self._default_config)
        with self._lock:
            if self._config_path.exists():
                try:
                    current = json.loads(self._config_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    _warn_runtime_config_issue(
                        self._config_path,
                        "runtime_manager_save_json_decode_error",
                        f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}",
                    )
                    current = {}
                if isinstance(current, dict):
                    merged.update(current)
                else:
                    _warn_runtime_config_issue(
                        self._config_path,
                        "runtime_manager_save_non_object_payload",
                        f"expected a JSON object, got {type(current).__name__}",
                    )
            merged.update(payload)
            self._config_path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2),
                encoding="utf-8",
                newline="\n",
            )
            return merged

    def get_rag_mode(self) -> bool:
        return bool(self.load().get("rag_mode", False))

    def set_rag_mode(self, enabled: bool) -> dict[str, Any]:
        return self.save({"rag_mode": enabled})

    def get_permission_mode(self) -> str:
        return _normalize_runtime_permission_mode(self.load().get("permission_mode", "default"))

    def set_permission_mode(self, mode: str) -> dict[str, Any]:
        normalized = _normalize_runtime_permission_mode(mode)
        return self.save({"permission_mode": normalized})

    def get_orchestration_plan_mode(self) -> str:
        return "primary"

    def set_orchestration_plan_mode(self, mode: str) -> dict[str, Any]:
        return self.save({"orchestration_plan_mode": "primary"})

    def get_context_budget_preset(self) -> str:
        from context_system.budget.presets import normalize_context_budget_preset_id

        return normalize_context_budget_preset_id(str(self.load().get("context_budget_preset") or ""))

    def set_context_budget_preset(self, preset_id: str) -> dict[str, Any]:
        from context_system.budget.presets import normalize_context_budget_preset_id

        return self.save({"context_budget_preset": normalize_context_budget_preset_id(preset_id)})

    def get_code_environment_config(self) -> dict[str, Any]:
        payload = dict(self.load().get("code_environment") or {})
        default = dict(self._default_config.get("code_environment") or {})
        default_sidecar = dict(default.get("pi_sidecar") or {})
        sidecar = {**default_sidecar, **dict(payload.get("pi_sidecar") or {})}
        return {
            **default,
            **payload,
            "enabled": bool(payload.get("enabled", default.get("enabled", True))),
            "workspace_root_policy": str(payload.get("workspace_root_policy") or default.get("workspace_root_policy") or "project_root"),
            "pi_sidecar": sidecar,
        }

    def set_code_environment_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_code_environment_config()
        next_payload = dict(payload or {})
        sidecar = {**dict(current.get("pi_sidecar") or {}), **dict(next_payload.get("pi_sidecar") or {})}
        next_payload["pi_sidecar"] = sidecar
        return self.save({"code_environment": {**current, **next_payload}})

runtime_config = RuntimeConfigManager(get_settings().backend_dir / "config.json")


