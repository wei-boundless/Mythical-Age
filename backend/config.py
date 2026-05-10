from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from project_layout import ProjectLayout

LLM_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "zhipu": {
        "model": "glm-5",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/",
    },
    "bailian": {
        "model": "qwen3.5-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "deepseek": {
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
    },
    "openai": {
        "model": "gpt-4.1-mini",
        "base_url": "https://api.openai.com/v1",
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
    faiss_metric: str
    faiss_index_type: str
    faiss_hnsw_m: int
    faiss_hnsw_ef_construction: int
    faiss_hnsw_ef_search: int
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


def _provider_first_env(provider: str, specific_name: str, generic_name: str) -> str | None:
    """Resolve provider-bound config before global compatibility config.

    Global LLM_* env vars are kept as compatibility fallbacks, but they should
    not override provider-specific values once a provider has been selected.
    Otherwise a model name for one provider can silently enter another
    provider's candidate chain.
    """

    specific = _first_env(specific_name)
    if specific:
        return specific
    return _first_env(generic_name)


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


def _resolve_llm_api_key(provider: str) -> str | None:
    runtime_override = _runtime_llm_override()
    override_api_key = str(runtime_override.get("api_key") or "").strip()
    if override_api_key:
        return override_api_key
    if provider == "zhipu":
        return _first_env("LLM_API_KEY", "ZHIPU_API_KEY", "ZHIPUAI_API_KEY")
    if provider == "bailian":
        return _first_env("LLM_API_KEY", "BAILIAN_API_KEY", "DASHSCOPE_API_KEY")
    if provider == "deepseek":
        return _first_env("LLM_API_KEY", "DEEPSEEK_API_KEY")
    return _first_env("LLM_API_KEY", "OPENAI_API_KEY")


def _resolve_llm_model(provider: str) -> str:
    runtime_override = _runtime_llm_override()
    override_model = str(runtime_override.get("model") or "").strip()
    if override_model:
        return _normalize_llm_model_id(provider, override_model)
    if provider == "zhipu":
        model = _provider_first_env(provider, "ZHIPU_MODEL", "LLM_MODEL") or LLM_PROVIDER_DEFAULTS[provider]["model"]
        return _normalize_llm_model_id(provider, model)
    if provider == "bailian":
        model = _provider_first_env(provider, "BAILIAN_MODEL", "LLM_MODEL") or LLM_PROVIDER_DEFAULTS[provider]["model"]
        return _normalize_llm_model_id(provider, model)
    if provider == "deepseek":
        model = _provider_first_env(provider, "DEEPSEEK_MODEL", "LLM_MODEL") or LLM_PROVIDER_DEFAULTS[provider]["model"]
        return _normalize_llm_model_id(provider, model)
    model = _first_env("LLM_MODEL") or LLM_PROVIDER_DEFAULTS[provider]["model"]
    return _normalize_llm_model_id(provider, model)


def _resolve_llm_base_url(provider: str) -> str:
    runtime_override = _runtime_llm_override()
    override_base_url = str(runtime_override.get("base_url") or "").strip()
    if override_base_url:
        return override_base_url
    if provider == "zhipu":
        return _provider_first_env(provider, "ZHIPU_BASE_URL", "LLM_BASE_URL") or LLM_PROVIDER_DEFAULTS[provider]["base_url"]
    if provider == "bailian":
        return _provider_first_env(provider, "BAILIAN_BASE_URL", "LLM_BASE_URL") or LLM_PROVIDER_DEFAULTS[provider]["base_url"]
    if provider == "deepseek":
        return _provider_first_env(provider, "DEEPSEEK_BASE_URL", "LLM_BASE_URL") or LLM_PROVIDER_DEFAULTS[provider]["base_url"]
    return _first_env("LLM_BASE_URL", "OPENAI_BASE_URL") or LLM_PROVIDER_DEFAULTS[provider]["base_url"]


def _resolve_llm_fallback_provider() -> str | None:
    runtime_override = _runtime_llm_override()
    if "fallback_provider" in runtime_override:
        value = str(runtime_override.get("fallback_provider") or "").strip().lower()
        if value in {"", "none", "disabled", "off"}:
            return None
        return _normalize_provider(value, default="", defaults=LLM_PROVIDER_DEFAULTS) or None
    value = _first_env("LLM_FALLBACK_PROVIDER")
    if not value:
        return None
    normalized = _normalize_provider(value, default="", defaults=LLM_PROVIDER_DEFAULTS)
    return normalized or None


def _runtime_config_path() -> Path:
    return Path(__file__).resolve().parent / "config.json"


def _runtime_payload() -> dict[str, Any]:
    try:
        payload = json.loads(_runtime_config_path().read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


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
    if provider == "zhipu":
        return _first_env("LLM_FALLBACK_API_KEY", "ZHIPU_API_KEY", "ZHIPUAI_API_KEY")
    if provider == "bailian":
        return _first_env("LLM_FALLBACK_API_KEY", "BAILIAN_API_KEY", "DASHSCOPE_API_KEY")
    if provider == "deepseek":
        return _first_env("LLM_FALLBACK_API_KEY", "DEEPSEEK_API_KEY")
    return _first_env("LLM_FALLBACK_API_KEY", "OPENAI_API_KEY")


def _resolve_llm_fallback_model(provider: str | None) -> str | None:
    if not provider:
        return None
    runtime_override = _runtime_llm_override()
    override_model = str(runtime_override.get("fallback_model") or "").strip()
    if override_model:
        return _normalize_llm_model_id(provider, override_model)
    if provider == "zhipu":
        model = _provider_first_env(provider, "ZHIPU_MODEL", "LLM_FALLBACK_MODEL") or LLM_PROVIDER_DEFAULTS[provider]["model"]
        return _normalize_llm_model_id(provider, model)
    if provider == "bailian":
        model = _provider_first_env(provider, "BAILIAN_MODEL", "LLM_FALLBACK_MODEL") or LLM_PROVIDER_DEFAULTS[provider]["model"]
        return _normalize_llm_model_id(provider, model)
    if provider == "deepseek":
        model = _provider_first_env(provider, "DEEPSEEK_MODEL", "LLM_FALLBACK_MODEL") or LLM_PROVIDER_DEFAULTS[provider]["model"]
        return _normalize_llm_model_id(provider, model)
    model = _first_env("LLM_FALLBACK_MODEL") or LLM_PROVIDER_DEFAULTS[provider]["model"]
    return _normalize_llm_model_id(provider, model)


def _resolve_llm_fallback_base_url(provider: str | None) -> str | None:
    if not provider:
        return None
    runtime_override = _runtime_llm_override()
    override_base_url = str(runtime_override.get("fallback_base_url") or "").strip()
    if override_base_url:
        return override_base_url
    if provider == "zhipu":
        return _provider_first_env(provider, "ZHIPU_BASE_URL", "LLM_FALLBACK_BASE_URL") or LLM_PROVIDER_DEFAULTS[provider]["base_url"]
    if provider == "bailian":
        return _provider_first_env(provider, "BAILIAN_BASE_URL", "LLM_FALLBACK_BASE_URL") or LLM_PROVIDER_DEFAULTS[provider]["base_url"]
    if provider == "deepseek":
        return _provider_first_env(provider, "DEEPSEEK_BASE_URL", "LLM_FALLBACK_BASE_URL") or LLM_PROVIDER_DEFAULTS[provider]["base_url"]
    return _first_env("LLM_FALLBACK_BASE_URL", "OPENAI_BASE_URL") or LLM_PROVIDER_DEFAULTS[provider]["base_url"]


def _resolve_llm_thinking_mode() -> str:
    value = str(_runtime_system_value("runtime", "llm_thinking_mode") or os.getenv("LLM_THINKING_MODE") or "disabled").strip().lower()
    if value in {"on", "true", "1", "enabled", "enable"}:
        return "enabled"
    if value in {"off", "false", "0", "disabled", "disable"}:
        return "disabled"
    return "disabled"


def _resolve_llm_reasoning_effort() -> str:
    value = str(_runtime_system_value("runtime", "llm_reasoning_effort") or os.getenv("LLM_REASONING_EFFORT") or "high").strip().lower()
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
    if override in {"faiss", "llamaindex", "qdrant"}:
        return override
    value = (_first_env("VECTOR_STORE_BACKEND") or "qdrant").strip().lower()
    if value in {"faiss", "llamaindex", "qdrant"}:
        return value
    return "qdrant"


def _resolve_document_conversion_backend() -> str:
    override = str(_runtime_system_value("document", "document_conversion_backend") or "").strip().lower()
    if override in {"docling", "legacy"}:
        return override
    value = (_first_env("DOCUMENT_CONVERSION_BACKEND") or "docling").strip().lower()
    if value in {"docling", "legacy"}:
        return value
    return "docling"


def _resolve_retrieval_core_backend() -> str:
    override = str(_runtime_system_value("retrieval", "retrieval_core_backend") or "").strip().lower()
    if override in {"legacy", "llamaindex"}:
        return override
    value = (_first_env("RETRIEVAL_CORE_BACKEND") or "llamaindex").strip().lower()
    if value in {"legacy", "llamaindex"}:
        return value
    return "llamaindex"


def _resolve_faiss_metric() -> str:
    override = str(_runtime_system_value("retrieval", "faiss_metric") or "").strip().lower()
    if override in {"cosine", "inner_product", "l2"}:
        return override
    value = (_first_env("FAISS_METRIC") or "cosine").strip().lower()
    if value in {"cosine", "inner_product", "l2"}:
        return value
    return "cosine"


def _resolve_faiss_index_type() -> str:
    override = str(_runtime_system_value("retrieval", "faiss_index_type") or "").strip().lower()
    if override in {"flat", "hnsw"}:
        return override
    value = (_first_env("FAISS_INDEX_TYPE") or "flat").strip().lower()
    if value in {"flat", "hnsw"}:
        return value
    return "flat"


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
        default="zhipu",
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
        llm_max_output_tokens=_resolve_positive_int("LLM_MAX_OUTPUT_TOKENS", 32768, _runtime_system_value("runtime", "llm_max_output_tokens")),
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
        faiss_metric=_resolve_faiss_metric(),
        faiss_index_type=_resolve_faiss_index_type(),
        faiss_hnsw_m=_resolve_positive_int("FAISS_HNSW_M", 32),
        faiss_hnsw_ef_construction=_resolve_positive_int("FAISS_HNSW_EF_CONSTRUCTION", 40),
        faiss_hnsw_ef_search=_resolve_positive_int("FAISS_HNSW_EF_SEARCH", 64),
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
        }

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self._config_path.exists():
                self.save(self._default_config)
            try:
                return json.loads(self._config_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.save(self._default_config)
                return dict(self._default_config)

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        merged = dict(self._default_config)
        with self._lock:
            if self._config_path.exists():
                try:
                    current = json.loads(self._config_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    current = {}
                if isinstance(current, dict):
                    merged.update(current)
            merged.update(payload)
            self._config_path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return merged

    def get_rag_mode(self) -> bool:
        return bool(self.load().get("rag_mode", False))

    def set_rag_mode(self, enabled: bool) -> dict[str, Any]:
        return self.save({"rag_mode": enabled})

    def get_permission_mode(self) -> str:
        return str(self.load().get("permission_mode", "default") or "default")

    def set_permission_mode(self, mode: str) -> dict[str, Any]:
        normalized = (mode or "default").strip() or "default"
        return self.save({"permission_mode": normalized})

    def get_orchestration_plan_mode(self) -> str:
        return "primary"

    def set_orchestration_plan_mode(self, mode: str) -> dict[str, Any]:
        return self.save({"orchestration_plan_mode": "primary"})

    def get_context_budget_preset(self) -> str:
        from context_management.budget_presets import normalize_context_budget_preset_id

        return normalize_context_budget_preset_id(str(self.load().get("context_budget_preset") or ""))

    def set_context_budget_preset(self, preset_id: str) -> dict[str, Any]:
        from context_management.budget_presets import normalize_context_budget_preset_id

        return self.save({"context_budget_preset": normalize_context_budget_preset_id(preset_id)})


runtime_config = RuntimeConfigManager(get_settings().backend_dir / "config.json")
