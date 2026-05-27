from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import EMBEDDING_PROVIDER_DEFAULTS, LLM_PROVIDER_DEFAULTS, Settings, get_settings, runtime_config
from context_system.budget.presets import (
    get_context_budget_preset,
    list_context_budget_presets,
)
from soul.image_asset_service import SoulImageAssetService


def _provider_hint_from_model_base_url(model: str | None, base_url: str | None) -> str:
    haystack = f"{model or ''} {base_url or ''}".strip().lower()
    if not haystack:
        return ""
    if "deepseek" in haystack or "api.deepseek.com" in haystack:
        return "deepseek"
    if "dashscope" in haystack or "aliyuncs.com" in haystack or "qwen" in haystack:
        return "bailian"
    if "bigmodel" in haystack or "zhipu" in haystack or "glm-" in haystack:
        return "zhipu"
    if "api.openai.com" in haystack or haystack.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    return ""


def _normalize_provider_with_payload_hints(provider: str, model: str | None, base_url: str | None) -> str:
    normalized = str(provider or "").strip().lower()
    hint = _provider_hint_from_model_base_url(model, base_url)
    if hint and normalized and hint != normalized:
        return hint
    return normalized or hint


@dataclass(frozen=True, slots=True)
class RuntimeSettingsSnapshot:
    rag_mode: bool
    orchestration_plan_mode: str


@dataclass(frozen=True, slots=True)
class PolicySettingsSnapshot:
    permission_mode: str


@dataclass(frozen=True, slots=True)
class StaticSettingsSnapshot:
    llm_provider: str
    llm_model: str
    llm_timeout_seconds: float
    llm_max_retries: int
    llm_max_output_tokens: int
    llm_long_output_timeout_seconds: float
    llm_thinking_mode: str
    llm_reasoning_effort: str
    embedding_provider: str
    embedding_model: str
    vector_store_backend: str
    document_conversion_backend: str
    retrieval_core_backend: str
    component_char_limit: int
    terminal_timeout_seconds: int


class AppSettingsService:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self._static_settings = get_settings()

    @property
    def static(self) -> Settings:
        return get_settings()

    def static_snapshot(self) -> StaticSettingsSnapshot:
        settings = self.static
        return StaticSettingsSnapshot(
            llm_provider=settings.llm_provider,
            llm_model=settings.llm_model,
            llm_timeout_seconds=settings.llm_timeout_seconds,
            llm_max_retries=settings.llm_max_retries,
            llm_max_output_tokens=settings.llm_max_output_tokens,
            llm_long_output_timeout_seconds=settings.llm_long_output_timeout_seconds,
            llm_thinking_mode=settings.llm_thinking_mode,
            llm_reasoning_effort=settings.llm_reasoning_effort,
            embedding_provider=settings.embedding_provider,
            embedding_model=settings.embedding_model,
            vector_store_backend=settings.vector_store_backend,
            document_conversion_backend=settings.document_conversion_backend,
            retrieval_core_backend=settings.retrieval_core_backend,
            component_char_limit=settings.component_char_limit,
            terminal_timeout_seconds=settings.terminal_timeout_seconds,
        )

    def runtime_snapshot(self) -> RuntimeSettingsSnapshot:
        payload = runtime_config.load()
        return RuntimeSettingsSnapshot(
            rag_mode=bool(payload.get("rag_mode", False)),
            orchestration_plan_mode="primary",
        )

    def policy_snapshot(self) -> PolicySettingsSnapshot:
        payload = runtime_config.load()
        return PolicySettingsSnapshot(
            permission_mode=str(payload.get("permission_mode", "default") or "default"),
        )

    def get_rag_mode(self) -> bool:
        return bool(runtime_config.get_rag_mode())

    def set_rag_mode(self, enabled: bool) -> dict[str, Any]:
        return runtime_config.set_rag_mode(enabled)

    def get_permission_mode(self) -> str:
        getter = getattr(runtime_config, "get_permission_mode", None)
        if callable(getter):
            return str(getter() or "default")
        return str(self.policy_snapshot().permission_mode or "default")

    def set_permission_mode(self, mode: str) -> dict[str, Any]:
        setter = getattr(runtime_config, "set_permission_mode", None)
        if callable(setter):
            return setter(mode)
        current = runtime_config.load()
        current["permission_mode"] = mode
        return runtime_config.save(current)

    def get_orchestration_plan_mode(self) -> str:
        getter = getattr(runtime_config, "get_orchestration_plan_mode", None)
        if callable(getter):
            return str(getter() or "primary")
        return "primary"

    def set_orchestration_plan_mode(self, mode: str) -> dict[str, Any]:
        setter = getattr(runtime_config, "set_orchestration_plan_mode", None)
        if callable(setter):
            return setter(mode)
        current = runtime_config.load()
        current["orchestration_plan_mode"] = "primary"
        return runtime_config.save(current)

    def get_context_budget_preset(self) -> str:
        getter = getattr(runtime_config, "get_context_budget_preset", None)
        if callable(getter):
            return str(getter() or "deepseek_1m")
        return "deepseek_1m"

    def set_context_budget_preset(self, preset_id: str) -> dict[str, Any]:
        setter = getattr(runtime_config, "set_context_budget_preset", None)
        if callable(setter):
            return setter(preset_id)
        current = runtime_config.load()
        current["context_budget_preset"] = str(preset_id or "deepseek_1m")
        return runtime_config.save(current)

    def context_budget_settings(self) -> dict[str, Any]:
        preset = get_context_budget_preset(self.get_context_budget_preset())
        return preset.to_dict()

    def context_budget_payload(self) -> dict[str, Any]:
        active = self.context_budget_settings()
        return {
            "active_preset": active,
            "preset_id": active["preset_id"],
            "presets": list_context_budget_presets(),
            "authority": "runtime.context_budget_presets",
        }

    def model_provider_payload(self) -> dict[str, Any]:
        from agent_system.models.model_profile_resolver import build_provider_catalog

        settings = self.static
        provider_catalog = build_provider_catalog(self)
        return {
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "base_url": settings.llm_base_url,
            "credential_ref": f"provider:{settings.llm_provider}:primary",
            "api_key_configured": bool(settings.llm_api_key),
            "thinking_mode": settings.llm_thinking_mode,
            "reasoning_effort": settings.llm_reasoning_effort,
            "fallback_provider": settings.llm_fallback_provider or "",
            "fallback_model": settings.llm_fallback_model or "",
            "fallback_base_url": settings.llm_fallback_base_url or "",
            "fallback_credential_ref": f"provider:{settings.llm_fallback_provider}:fallback" if settings.llm_fallback_provider else "",
            "fallback_api_key_configured": bool(settings.llm_fallback_api_key),
            "supported_providers": provider_catalog["providers"],
            "provider_catalog": provider_catalog,
            "authority": "runtime.model_provider",
        }

    def set_model_provider(
        self,
        *,
        provider: str,
        model: str,
        base_url: str,
        api_key: str | None = None,
        fallback_provider: str | None = None,
        fallback_model: str | None = None,
        fallback_base_url: str | None = None,
        fallback_api_key: str | None = None,
    ) -> dict[str, Any]:
        from config import get_settings as cached_get_settings

        normalized_provider = _normalize_provider_with_payload_hints(provider, model, base_url)
        if normalized_provider not in LLM_PROVIDER_DEFAULTS:
            normalized_provider = self.static.llm_provider
        defaults = LLM_PROVIDER_DEFAULTS[normalized_provider]
        payload: dict[str, Any] = {
            "provider": normalized_provider,
            "model": str(model or defaults["model"]).strip() or defaults["model"],
            "base_url": str(base_url or defaults["base_url"]).strip() or defaults["base_url"],
        }
        normalized_fallback_provider = _normalize_provider_with_payload_hints(
            str(fallback_provider or ""),
            fallback_model,
            fallback_base_url,
        )
        if normalized_fallback_provider in {"none", "disabled", "off"}:
            normalized_fallback_provider = ""
        if normalized_fallback_provider and normalized_fallback_provider not in LLM_PROVIDER_DEFAULTS:
            normalized_fallback_provider = self.static.llm_fallback_provider or ""
        if normalized_fallback_provider:
            fallback_defaults = LLM_PROVIDER_DEFAULTS[normalized_fallback_provider]
            payload["fallback_provider"] = normalized_fallback_provider
            payload["fallback_model"] = str(fallback_model or fallback_defaults["model"]).strip() or fallback_defaults["model"]
            payload["fallback_base_url"] = str(fallback_base_url or fallback_defaults["base_url"]).strip() or fallback_defaults["base_url"]
        elif fallback_provider is not None:
            payload["fallback_provider"] = ""
            payload["fallback_model"] = ""
            payload["fallback_base_url"] = ""
        if api_key is not None and str(api_key).strip():
            payload["api_key"] = str(api_key).strip()
        else:
            current = dict(runtime_config.load().get("model_provider") or {})
            existing_key = str(current.get("api_key") or "").strip()
            if existing_key:
                payload["api_key"] = existing_key
        if normalized_fallback_provider:
            if fallback_api_key is not None and str(fallback_api_key).strip():
                payload["fallback_api_key"] = str(fallback_api_key).strip()
            else:
                current = dict(runtime_config.load().get("model_provider") or {})
                existing_key = str(current.get("fallback_api_key") or "").strip()
                if existing_key:
                    payload["fallback_api_key"] = existing_key
        runtime_config.save({"model_provider": payload})
        cache_clear = getattr(cached_get_settings, "cache_clear", None)
        if callable(cache_clear):
            cache_clear()
        return self.model_provider_payload()

    def _system_config_overrides(self) -> dict[str, Any]:
        payload = runtime_config.load()
        config = payload.get("system_config")
        return dict(config) if isinstance(config, dict) else {}

    def _system_section_overrides(self, section: str) -> dict[str, Any]:
        config = self._system_config_overrides()
        section_payload = config.get(section)
        return dict(section_payload) if isinstance(section_payload, dict) else {}

    def _field(
        self,
        *,
        section: str,
        key: str,
        label: str,
        field_type: str,
        value: Any = None,
        configured: bool | None = None,
        options: list[str] | None = None,
        description: str = "",
        restart_required: bool = False,
    ) -> dict[str, Any]:
        overrides = self._system_section_overrides(section)
        payload: dict[str, Any] = {
            "key": key,
            "label": label,
            "type": field_type,
            "source": "runtime_override" if key in overrides else "env_or_default",
            "description": description,
            "restart_required": restart_required,
        }
        if field_type == "secret":
            payload["configured"] = bool(configured)
        else:
            payload["value"] = value
        if options:
            payload["options"] = options
        return payload

    def runtime_config_console_payload(self) -> dict[str, Any]:
        settings = self.static
        model_payload = self.model_provider_payload()
        budget_payload = self.context_budget_payload()
        model_overrides = dict(runtime_config.load().get("model_provider") or {})
        image_service = SoulImageAssetService(self.base_dir)
        image_payload = image_service.config_summary()
        image_overrides = dict(runtime_config.load().get("soul_image_assets") or {})

        model_group = {
            "group_id": "model",
            "title": "系统默认模型与凭据底座",
            "description": "控制系统默认模型、接入端点、密钥和备用模型；Agent 可以在编排系统中覆盖模型运行档案。",
            "status": f"{settings.llm_provider} / {settings.llm_model}"
            + (f" -> {settings.llm_fallback_provider} / {settings.llm_fallback_model}" if settings.llm_fallback_provider else ""),
            "fields": [
                {
                    "key": "provider",
                    "label": "主模型 Provider",
                    "type": "select",
                    "value": settings.llm_provider,
                    "options": list(LLM_PROVIDER_DEFAULTS.keys()),
                    "source": "runtime_override" if "provider" in model_overrides else "env_or_default",
                    "description": "系统默认模型服务商；Agent 未覆盖时继承这里。",
                    "restart_required": False,
                },
                {
                    "key": "model",
                    "label": "主模型名称",
                    "type": "text",
                    "value": settings.llm_model,
                    "source": "runtime_override" if "model" in model_overrides else "env_or_default",
                    "description": "系统默认模型名称；DeepSeek 为当前推荐底座。",
                    "restart_required": False,
                },
                {
                    "key": "base_url",
                    "label": "主模型 Base URL",
                    "type": "text",
                    "value": settings.llm_base_url,
                    "source": "runtime_override" if "base_url" in model_overrides else "env_or_default",
                    "description": "供应商 API 接入地址；Agent 不单独配置这个地址。",
                    "restart_required": False,
                },
                {
                    "key": "api_key",
                    "label": "主模型 API Key",
                    "type": "secret",
                    "configured": bool(settings.llm_api_key),
                    "source": "runtime_override" if "api_key" in model_overrides else "env_or_default",
                    "description": "留空保存会保留已有密钥；Agent 只会引用这份主模型密钥。",
                    "restart_required": False,
                },
                {
                    "key": "fallback_provider",
                    "label": "备用模型 Provider",
                    "type": "select",
                    "value": settings.llm_fallback_provider or "",
                    "options": ["", *list(LLM_PROVIDER_DEFAULTS.keys())],
                    "source": "runtime_override" if "fallback_provider" in model_overrides else "env_or_default",
                    "description": "留空表示关闭备用模型。",
                    "restart_required": False,
                },
                {
                    "key": "fallback_model",
                    "label": "备用模型名称",
                    "type": "text",
                    "value": settings.llm_fallback_model or "",
                    "source": "runtime_override" if "fallback_model" in model_overrides else "env_or_default",
                    "description": "备用模型名称；关闭备用模型时可留空。",
                    "restart_required": False,
                },
                {
                    "key": "fallback_base_url",
                    "label": "备用模型 Base URL",
                    "type": "text",
                    "value": settings.llm_fallback_base_url or "",
                    "source": "runtime_override" if "fallback_base_url" in model_overrides else "env_or_default",
                    "description": "备用模型 endpoint。",
                    "restart_required": False,
                },
                {
                    "key": "fallback_api_key",
                    "label": "备用模型 API Key",
                    "type": "secret",
                    "configured": bool(settings.llm_fallback_api_key),
                    "source": "runtime_override" if "fallback_api_key" in model_overrides else "env_or_default",
                    "description": "留空保存会保留已有密钥。",
                    "restart_required": False,
                },
            ],
            "metadata": {
                "supported_providers": model_payload["supported_providers"],
                "provider_catalog": model_payload["provider_catalog"],
                "credential_refs": model_payload["provider_catalog"]["credential_refs"],
            },
        }

        context_group = {
            "group_id": "context",
            "title": "上下文预算",
            "description": "控制上下文压缩、水位线和长期记忆切片规模。",
            "status": budget_payload["active_preset"]["title"],
            "fields": [],
            "metadata": budget_payload,
        }
        image_group = {
            "group_id": "soul_image_assets",
            "title": "生图模型",
            "description": "控制写作图、角色图和世界观图使用的 OpenAI-compatible 生图服务。",
            "status": "已配置" if image_payload["configured"] else "配置不完整",
            "fields": [
                {
                    "key": "base_url",
                    "label": "Base URL",
                    "type": "text",
                    "value": image_payload["base_url"],
                    "source": "runtime_override" if "base_url" in image_overrides else "env_or_default",
                    "description": "生图 API 接入地址，系统会调用其 /images/generations。",
                    "restart_required": False,
                },
                {
                    "key": "model",
                    "label": "模型",
                    "type": "text",
                    "value": image_payload["model"],
                    "source": "runtime_override" if "model" in image_overrides else "env_or_default",
                    "description": "生图模型名称，例如 gpt-image-2。",
                    "restart_required": False,
                },
                {
                    "key": "api_key",
                    "label": "API Key",
                    "type": "secret",
                    "configured": bool(image_payload["api_key_present"]),
                    "source": "runtime_override" if "api_key" in image_overrides else "env_or_default",
                    "description": "留空保存会保留已有密钥。",
                    "restart_required": False,
                },
            ],
            "metadata": {
                "public_dir": image_payload["public_dir"],
            },
        }
        rerank_mode = "disabled"
        if settings.rerank_enabled:
            provider = (settings.rerank_provider or "heuristic").strip().lower()
            if provider == "heuristic":
                rerank_mode = "heuristic"
            elif provider in {"cross_encoder", "sentence_transformers", "huggingface"}:
                rerank_mode = "local"
            elif provider in {"bailian", "dashscope", "qwen", "remote_api", "remote"}:
                rerank_mode = "api"
            else:
                rerank_mode = "heuristic"

        return {
            "authority": "runtime.system_config_console",
            "groups": [
                model_group,
                {
                    "group_id": "embedding",
                    "title": "Embedding",
                    "description": "控制向量化 Provider、模型、维度和密钥。",
                    "status": f"{settings.embedding_provider} / {settings.embedding_model}",
                    "fields": [
                        self._field(section="embedding", key="provider", label="Provider", field_type="select", value=settings.embedding_provider, options=list(EMBEDDING_PROVIDER_DEFAULTS.keys()), description="Embedding 服务商。"),
                        self._field(section="embedding", key="model", label="Model", field_type="text", value=settings.embedding_model, description="Embedding 模型名。"),
                        self._field(section="embedding", key="base_url", label="Base URL", field_type="text", value=settings.embedding_base_url, description="Embedding endpoint。"),
                        self._field(section="embedding", key="dimensions", label="Dimensions", field_type="number", value=settings.embedding_dimensions or 1024, description="向量维度。"),
                        self._field(section="embedding", key="api_key", label="API Key", field_type="secret", configured=bool(settings.embedding_api_key), description="留空保存会保留已有密钥。"),
                    ],
                    "metadata": {
                        "supported_providers": EMBEDDING_PROVIDER_DEFAULTS,
                    },
                },
                {
                    "group_id": "retrieval",
                    "title": "检索与重排",
                    "description": "控制 RAG 后端、向量库、Qdrant 和 rerank 参数。",
                    "status": f"{settings.retrieval_core_backend} / {settings.vector_store_backend}",
                    "fields": [
                        self._field(section="retrieval", key="retrieval_core_backend", label="Retrieval Core", field_type="select", value=settings.retrieval_core_backend, options=["llamaindex"], description="当前正式检索核心实现。"),
                        self._field(section="retrieval", key="vector_store_backend", label="Vector Store", field_type="select", value=settings.vector_store_backend, options=["qdrant"], description="当前正式向量存储后端。"),
                        self._field(section="retrieval", key="qdrant_url", label="Qdrant URL", field_type="text", value=settings.qdrant_url or "", description="Qdrant 服务地址。"),
                        self._field(section="retrieval", key="qdrant_collection_prefix", label="Collection Prefix", field_type="text", value=settings.qdrant_collection_prefix, description="Qdrant collection 前缀。"),
                        self._field(section="retrieval", key="qdrant_api_key", label="Qdrant API Key", field_type="secret", configured=bool(settings.qdrant_api_key), description="留空保存会保留已有密钥。"),
                        self._field(section="retrieval", key="rerank_mode", label="Rerank 模式", field_type="select", value=rerank_mode, options=["disabled", "heuristic", "local", "api"], description="关闭、轻量启发式、本地 cross-encoder、远程 API 四选一。"),
                        self._field(section="retrieval", key="rerank_local_model", label="本地 Rerank 模型", field_type="text", value=settings.rerank_model or "", description="仅在本地模型模式使用，例如 cross-encoder 模型名。"),
                        self._field(section="retrieval", key="rerank_device", label="本地设备", field_type="text", value=settings.rerank_device or "", description="仅本地模型模式使用，例如 cpu、cuda。"),
                        self._field(section="retrieval", key="rerank_api_provider", label="API Provider", field_type="select", value=settings.rerank_provider if rerank_mode == "api" else "bailian", options=["bailian", "dashscope", "qwen", "remote_api", "remote"], description="仅 API 模式使用。"),
                        self._field(section="retrieval", key="rerank_api_model", label="API Rerank 模型", field_type="text", value=settings.rerank_model or "", description="仅 API 模式使用。"),
                        self._field(section="retrieval", key="rerank_api_base_url", label="API Base URL", field_type="text", value=settings.rerank_base_url or "", description="仅 API 模式使用。"),
                        self._field(section="retrieval", key="rerank_api_key", label="API Key", field_type="secret", configured=bool(settings.rerank_api_key), description="仅 API 模式使用；留空保存会保留已有密钥。"),
                        self._field(section="retrieval", key="rerank_top_n", label="Rerank Top N", field_type="number", value=settings.rerank_top_n, description="最终返回的重排条数。"),
                        self._field(section="retrieval", key="rerank_candidate_pool", label="Candidate Pool", field_type="number", value=settings.rerank_candidate_pool, description="进入 rerank 的候选池大小。"),
                        self._field(section="retrieval", key="rerank_batch_size", label="Batch Size", field_type="number", value=settings.rerank_batch_size, description="本地模型批大小。"),
                        self._field(section="retrieval", key="rerank_max_length", label="Max Length", field_type="number", value=settings.rerank_max_length, description="本地模型输入最大长度。"),
                    ],
                },
                {
                    "group_id": "document",
                    "title": "文档解析",
                    "description": "控制 Docling、MinerU 和文档转换链路。",
                    "status": f"{settings.document_conversion_backend} / {'MinerU on' if settings.mineru_api_enabled else 'MinerU off'}",
                    "fields": [
                        self._field(section="document", key="document_conversion_backend", label="Conversion Backend", field_type="select", value=settings.document_conversion_backend, options=["docling"], description="文档转换后端。"),
                        self._field(section="document", key="docling_enabled", label="Docling Enabled", field_type="boolean", value=settings.docling_enabled, description="是否启用 Docling。"),
                        self._field(section="document", key="docling_prefer_ocr", label="Prefer OCR", field_type="boolean", value=settings.docling_prefer_ocr, description="Docling 是否优先 OCR。"),
                        self._field(section="document", key="mineru_api_enabled", label="MinerU Enabled", field_type="boolean", value=settings.mineru_api_enabled, description="是否启用 MinerU API。"),
                        self._field(section="document", key="mineru_api_mode", label="MinerU Mode", field_type="select", value=settings.mineru_api_mode, options=["local_sync", "cloud_v4_batch"], description="MinerU API 模式。"),
                        self._field(section="document", key="mineru_api_base_url", label="MinerU Base URL", field_type="text", value=settings.mineru_api_base_url or "", description="MinerU 服务地址。"),
                        self._field(section="document", key="mineru_api_parse_path", label="Parse Path", field_type="text", value=settings.mineru_api_parse_path, description="MinerU 解析路径。"),
                        self._field(section="document", key="mineru_api_key", label="MinerU API Key", field_type="secret", configured=bool(settings.mineru_api_key), description="留空保存会保留已有密钥。"),
                        self._field(section="document", key="mineru_api_timeout_seconds", label="Timeout Seconds", field_type="number", value=settings.mineru_api_timeout_seconds, description="MinerU API 超时时间。"),
                    ],
                },
                {
                    "group_id": "runtime",
                    "title": "运行限制与长输出",
                    "description": "控制模型调用重试、超时、最大输出 token、Thinking 模式和命令/组件边界。",
                    "status": f"{settings.llm_timeout_seconds:g}s / {settings.llm_max_output_tokens} tokens",
                    "fields": [
                        self._field(section="runtime", key="llm_timeout_seconds", label="LLM Timeout", field_type="number", value=settings.llm_timeout_seconds, description="主模型请求超时时间。"),
                        self._field(section="runtime", key="llm_long_output_timeout_seconds", label="长输出 Timeout", field_type="number", value=settings.llm_long_output_timeout_seconds, description="当设置最大输出 token 时使用的长输出请求超时时间。"),
                        self._field(section="runtime", key="llm_max_retries", label="LLM Max Retries", field_type="number", value=settings.llm_max_retries, description="主模型最大重试次数。"),
                        self._field(section="runtime", key="llm_max_output_tokens", label="最大输出 Tokens", field_type="number", value=settings.llm_max_output_tokens, description="传给模型的单次 completion 输出上限；DeepSeek V4 Pro 官方最大可到 384K tokens，但建议先按 32768/65536 实测。"),
                        self._field(section="runtime", key="llm_thinking_mode", label="Thinking 模式", field_type="select", value=settings.llm_thinking_mode, options=["disabled", "enabled"], description="长篇正文建议关闭；需要推理审查时再开启。DeepSeek 默认 thinking，系统会显式传入该配置。"),
                        self._field(section="runtime", key="llm_reasoning_effort", label="推理强度", field_type="select", value=settings.llm_reasoning_effort, options=["high", "max"], description="Thinking 开启时传给 DeepSeek 的 reasoning_effort。"),
                        self._field(section="runtime", key="terminal_timeout_seconds", label="Terminal Timeout", field_type="number", value=settings.terminal_timeout_seconds, description="终端默认超时时间。"),
                        self._field(section="runtime", key="component_char_limit", label="Component Char Limit", field_type="number", value=settings.component_char_limit, description="组件内容字符限制。"),
                    ],
                },
                image_group,
                context_group,
            ],
        }

    def set_runtime_config_group(self, group_id: str, values: dict[str, Any]) -> dict[str, Any]:
        from config import get_settings as cached_get_settings

        if group_id == "model":
            self.set_model_provider(
                provider=str(values.get("provider") or self.static.llm_provider),
                model=str(values.get("model") or self.static.llm_model),
                base_url=str(values.get("base_url") or self.static.llm_base_url),
                api_key=str(values.get("api_key") or "").strip() or None,
                fallback_provider=str(values.get("fallback_provider") or ""),
                fallback_model=str(values.get("fallback_model") or ""),
                fallback_base_url=str(values.get("fallback_base_url") or ""),
                fallback_api_key=str(values.get("fallback_api_key") or "").strip() or None,
            )
            return self.runtime_config_console_payload()
        if group_id == "soul_image_assets":
            SoulImageAssetService(self.base_dir).set_config(
                base_url=str(values.get("base_url") or ""),
                model=str(values.get("model") or "gpt-image-2"),
                api_key=str(values.get("api_key") or "").strip() or None,
            )
            return self.runtime_config_console_payload()
        allowed_groups = {"embedding", "retrieval", "document", "runtime"}
        if group_id not in allowed_groups:
            return self.runtime_config_console_payload()

        current = runtime_config.load()
        system_config = current.get("system_config")
        if not isinstance(system_config, dict):
            system_config = {}
        section = dict(system_config.get(group_id) or {})
        if group_id == "retrieval":
            values = self._normalize_retrieval_values(values, section)
        for key, value in values.items():
            if value is None:
                continue
            if isinstance(value, str) and value.strip() == "":
                if key.endswith("api_key"):
                    continue
                section[key] = ""
                continue
            section[key] = value
        system_config[group_id] = section
        runtime_config.save({"system_config": system_config})
        cache_clear = getattr(cached_get_settings, "cache_clear", None)
        if callable(cache_clear):
            cache_clear()
        return self.runtime_config_console_payload()

    def _normalize_retrieval_values(self, values: dict[str, Any], current_section: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(values)
        mode = str(normalized.get("rerank_mode") or current_section.get("rerank_mode") or "").strip().lower()
        if not mode:
            enabled = bool(normalized.get("rerank_enabled", current_section.get("rerank_enabled", False)))
            provider = str(normalized.get("rerank_provider", current_section.get("rerank_provider", "heuristic")) or "heuristic").strip().lower()
            if not enabled:
                mode = "disabled"
            elif provider in {"cross_encoder", "sentence_transformers", "huggingface"}:
                mode = "local"
            elif provider in {"bailian", "dashscope", "qwen", "remote_api", "remote"}:
                mode = "api"
            else:
                mode = "heuristic"
        if mode not in {"disabled", "heuristic", "local", "api"}:
            mode = "heuristic"

        if mode == "disabled":
            normalized["rerank_enabled"] = False
            normalized["rerank_provider"] = "heuristic"
            normalized["rerank_model"] = ""
            normalized["rerank_base_url"] = ""
            normalized["rerank_device"] = ""
            normalized.pop("rerank_api_key", None)
        elif mode == "heuristic":
            normalized["rerank_enabled"] = True
            normalized["rerank_provider"] = "heuristic"
            normalized["rerank_model"] = ""
            normalized["rerank_base_url"] = ""
            normalized["rerank_device"] = ""
            normalized.pop("rerank_api_key", None)
        elif mode == "local":
            normalized["rerank_enabled"] = True
            normalized["rerank_provider"] = "cross_encoder"
            normalized["rerank_model"] = str(normalized.get("rerank_local_model") or current_section.get("rerank_model") or "").strip()
            normalized["rerank_base_url"] = ""
            normalized.pop("rerank_api_key", None)
        else:
            normalized["rerank_enabled"] = True
            normalized["rerank_provider"] = str(normalized.get("rerank_api_provider") or current_section.get("rerank_provider") or "bailian").strip().lower()
            normalized["rerank_model"] = str(normalized.get("rerank_api_model") or current_section.get("rerank_model") or "").strip()
            normalized["rerank_base_url"] = str(normalized.get("rerank_api_base_url") or current_section.get("rerank_base_url") or "").strip()
            api_key = str(normalized.get("rerank_api_key") or "").strip()
            if not api_key:
                normalized.pop("rerank_api_key", None)

        for alias in ("rerank_mode", "rerank_local_model", "rerank_api_provider", "rerank_api_model", "rerank_api_base_url"):
            normalized.pop(alias, None)
        return normalized


