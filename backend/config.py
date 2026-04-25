from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

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
    indexes_v2_root: Path
    document_cache_v2_root: Path
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
    if provider == "zhipu":
        return _first_env("LLM_API_KEY", "ZHIPU_API_KEY", "ZHIPUAI_API_KEY")
    if provider == "bailian":
        return _first_env("LLM_API_KEY", "BAILIAN_API_KEY", "DASHSCOPE_API_KEY")
    if provider == "deepseek":
        return _first_env("LLM_API_KEY", "DEEPSEEK_API_KEY")
    return _first_env("LLM_API_KEY", "OPENAI_API_KEY")


def _resolve_llm_model(provider: str) -> str:
    if provider == "zhipu":
        return _first_env("LLM_MODEL", "ZHIPU_MODEL") or LLM_PROVIDER_DEFAULTS[provider]["model"]
    if provider == "bailian":
        return _first_env("LLM_MODEL", "BAILIAN_MODEL") or LLM_PROVIDER_DEFAULTS[provider]["model"]
    if provider == "deepseek":
        return _first_env("LLM_MODEL", "DEEPSEEK_MODEL") or LLM_PROVIDER_DEFAULTS[provider]["model"]
    return _first_env("LLM_MODEL") or LLM_PROVIDER_DEFAULTS[provider]["model"]


def _resolve_llm_base_url(provider: str) -> str:
    if provider == "zhipu":
        return _first_env("LLM_BASE_URL", "ZHIPU_BASE_URL") or LLM_PROVIDER_DEFAULTS[provider]["base_url"]
    if provider == "bailian":
        return _first_env("LLM_BASE_URL", "BAILIAN_BASE_URL") or LLM_PROVIDER_DEFAULTS[provider]["base_url"]
    if provider == "deepseek":
        return _first_env("LLM_BASE_URL", "DEEPSEEK_BASE_URL") or LLM_PROVIDER_DEFAULTS[provider]["base_url"]
    return _first_env("LLM_BASE_URL", "OPENAI_BASE_URL") or LLM_PROVIDER_DEFAULTS[provider]["base_url"]


def _resolve_llm_fallback_provider() -> str | None:
    value = _first_env("LLM_FALLBACK_PROVIDER")
    if not value:
        return None
    normalized = _normalize_provider(value, default="", defaults=LLM_PROVIDER_DEFAULTS)
    return normalized or None


def _resolve_llm_fallback_api_key(provider: str | None) -> str | None:
    if not provider:
        return None
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
    if provider == "zhipu":
        return _first_env("LLM_FALLBACK_MODEL", "ZHIPU_MODEL") or LLM_PROVIDER_DEFAULTS[provider]["model"]
    if provider == "bailian":
        return _first_env("LLM_FALLBACK_MODEL", "BAILIAN_MODEL") or LLM_PROVIDER_DEFAULTS[provider]["model"]
    if provider == "deepseek":
        return _first_env("LLM_FALLBACK_MODEL", "DEEPSEEK_MODEL") or LLM_PROVIDER_DEFAULTS[provider]["model"]
    return _first_env("LLM_FALLBACK_MODEL") or LLM_PROVIDER_DEFAULTS[provider]["model"]


def _resolve_llm_fallback_base_url(provider: str | None) -> str | None:
    if not provider:
        return None
    if provider == "zhipu":
        return _first_env("LLM_FALLBACK_BASE_URL", "ZHIPU_BASE_URL") or LLM_PROVIDER_DEFAULTS[provider]["base_url"]
    if provider == "bailian":
        return _first_env("LLM_FALLBACK_BASE_URL", "BAILIAN_BASE_URL") or LLM_PROVIDER_DEFAULTS[provider]["base_url"]
    if provider == "deepseek":
        return _first_env("LLM_FALLBACK_BASE_URL", "DEEPSEEK_BASE_URL") or LLM_PROVIDER_DEFAULTS[provider]["base_url"]
    return _first_env("LLM_FALLBACK_BASE_URL", "OPENAI_BASE_URL") or LLM_PROVIDER_DEFAULTS[provider]["base_url"]


def _resolve_embedding_api_key(provider: str) -> str | None:
    if provider == "bailian":
        return _first_env("EMBEDDING_API_KEY", "BAILIAN_API_KEY", "DASHSCOPE_API_KEY")
    return _first_env("EMBEDDING_API_KEY", "OPENAI_API_KEY")


def _resolve_embedding_model(provider: str) -> str:
    return _first_env("EMBEDDING_MODEL") or EMBEDDING_PROVIDER_DEFAULTS[provider]["model"]


def _resolve_embedding_base_url(provider: str) -> str:
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
    raw = _first_env("EMBEDDING_DIMENSIONS")
    if not raw:
        return 1024
    try:
        value = int(raw)
    except ValueError:
        return 1024
    return value if value > 0 else 1024


def _resolve_vector_store_backend() -> str:
    value = (_first_env("VECTOR_STORE_BACKEND") or "qdrant").strip().lower()
    if value in {"faiss", "llamaindex", "qdrant"}:
        return value
    return "qdrant"


def _resolve_document_conversion_backend() -> str:
    value = (_first_env("DOCUMENT_CONVERSION_BACKEND") or "docling").strip().lower()
    if value in {"docling", "legacy"}:
        return value
    return "docling"


def _resolve_retrieval_core_backend() -> str:
    value = (_first_env("RETRIEVAL_CORE_BACKEND") or "llamaindex_v2").strip().lower()
    if value in {"legacy", "llamaindex_v2"}:
        return value
    return "llamaindex_v2"


def _resolve_faiss_metric() -> str:
    value = (_first_env("FAISS_METRIC") or "cosine").strip().lower()
    if value in {"cosine", "inner_product", "l2"}:
        return value
    return "cosine"


def _resolve_faiss_index_type() -> str:
    value = (_first_env("FAISS_INDEX_TYPE") or "flat").strip().lower()
    if value in {"flat", "hnsw"}:
        return value
    return "flat"


def _resolve_qdrant_url() -> str | None:
    value = _first_env("QDRANT_URL", "QDRANT_HOST")
    return value or None


def _resolve_qdrant_api_key() -> str | None:
    value = _first_env("QDRANT_API_KEY")
    return value or None


def _resolve_qdrant_collection_prefix() -> str:
    value = (_first_env("QDRANT_COLLECTION_PREFIX") or "agent").strip()
    return value or "agent"


def _resolve_positive_int(name: str, default: int) -> int:
    raw = _first_env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _resolve_nonnegative_int(name: str, default: int) -> int:
    raw = _first_env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def _resolve_positive_float(name: str, default: float) -> float:
    raw = _first_env(name)
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
    return _resolve_bool(os.getenv("DOCLING_ENABLED"), default=True)


def _resolve_docling_prefer_ocr() -> bool:
    return _resolve_bool(os.getenv("DOCLING_PREFER_OCR"), default=False)


def _resolve_rerank_provider() -> str:
    return (_first_env("RERANK_PROVIDER") or "heuristic").strip().lower()


def _resolve_rerank_model() -> str | None:
    value = _first_env("RERANK_MODEL")
    return value or None


def _resolve_rerank_api_key() -> str | None:
    value = _first_env("RERANK_API_KEY")
    return value or None


def _resolve_rerank_base_url() -> str | None:
    value = _first_env("RERANK_BASE_URL")
    return value or None


def _resolve_rerank_top_n() -> int:
    raw = _first_env("RERANK_TOP_N")
    if not raw:
        return 8
    try:
        value = int(raw)
    except ValueError:
        return 8
    return value if value > 0 else 8


def _resolve_rerank_candidate_pool() -> int:
    raw = _first_env("RERANK_CANDIDATE_POOL")
    if not raw:
        return 20
    try:
        value = int(raw)
    except ValueError:
        return 20
    return value if value > 0 else 20


def _resolve_rerank_batch_size() -> int:
    raw = _first_env("RERANK_BATCH_SIZE")
    if not raw:
        return 8
    try:
        value = int(raw)
    except ValueError:
        return 8
    return value if value > 0 else 8


def _resolve_rerank_max_length() -> int:
    raw = _first_env("RERANK_MAX_LENGTH")
    if not raw:
        return 512
    try:
        value = int(raw)
    except ValueError:
        return 512
    return value if value > 0 else 512


def _resolve_rerank_device() -> str | None:
    value = _first_env("RERANK_DEVICE")
    return value or None


def _resolve_mineru_api_base_url() -> str | None:
    value = _first_env("MINERU_API_BASE_URL", "MINERU_BASE_URL")
    return value or None


def _resolve_mineru_api_mode() -> str:
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
    value = _first_env("MINERU_API_PARSE_PATH", "MINERU_PARSE_PATH") or default
    normalized = value.strip()
    if not normalized:
        return default
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return normalized
    if not normalized.startswith("/"):
        return "/" + normalized
    return normalized


def _resolve_mineru_api_key() -> str | None:
    value = _first_env("MINERU_API_KEY", "MINERU_API_TOKEN")
    return value or None


def _resolve_mineru_api_timeout_seconds() -> int:
    return _resolve_positive_int("MINERU_API_TIMEOUT_SECONDS", 180)


def _resolve_mineru_api_enabled() -> bool:
    if not _resolve_bool(os.getenv("MINERU_API_ENABLED"), default=False):
        return False
    return bool(_resolve_mineru_api_base_url())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    backend_dir = _load_env_file()
    project_root = backend_dir.parent

    llm_provider = _normalize_provider(
        os.getenv("LLM_PROVIDER"),
        default="zhipu",
        defaults=LLM_PROVIDER_DEFAULTS,
    )
    embedding_provider = _normalize_provider(
        os.getenv("EMBEDDING_PROVIDER"),
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
        llm_timeout_seconds=_resolve_positive_float("LLM_TIMEOUT_SECONDS", 45.0),
        llm_max_retries=_resolve_nonnegative_int("LLM_MAX_RETRIES", 2),
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
        indexes_v2_root=backend_dir / "storage" / "indexes_v2",
        document_cache_v2_root=backend_dir / "storage" / "document_cache_v2",
        docling_enabled=_resolve_docling_enabled(),
        docling_prefer_ocr=_resolve_docling_prefer_ocr(),
        rerank_enabled=_resolve_bool(os.getenv("RERANK_ENABLED"), default=False),
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
    )


class RuntimeConfigManager:
    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path
        self._lock = threading.Lock()
        self._default_config = {
            "rag_mode": False,
            "permission_mode": "default",
            "retrieval_shadow_compare": False,
            "retrieval_cutover_mode": "v2_primary",
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

    def get_retrieval_shadow_compare(self) -> bool:
        return bool(self.load().get("retrieval_shadow_compare", False))

    def set_retrieval_shadow_compare(self, enabled: bool) -> dict[str, Any]:
        return self.save({"retrieval_shadow_compare": bool(enabled)})

    def get_retrieval_cutover_mode(self) -> str:
        value = str(self.load().get("retrieval_cutover_mode", "v2_primary") or "v2_primary").strip().lower()
        if value in {"legacy_only", "shadow_read", "v2_primary"}:
            return value
        return "v2_primary"

    def set_retrieval_cutover_mode(self, mode: str) -> dict[str, Any]:
        normalized = str(mode or "v2_primary").strip().lower() or "v2_primary"
        if normalized not in {"legacy_only", "shadow_read", "v2_primary"}:
            normalized = "v2_primary"
        return self.save({"retrieval_cutover_mode": normalized})


runtime_config = RuntimeConfigManager(get_settings().backend_dir / "config.json")
