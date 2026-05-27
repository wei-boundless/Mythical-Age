from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config


@pytest.fixture(autouse=True)
def _isolated_runtime_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    runtime_path = tmp_path / "config.json"
    runtime_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "_runtime_config_path", lambda: runtime_path)
    monkeypatch.setattr(config, "_load_env_file", lambda: BACKEND_DIR)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_settings_expose_llm_timeout_and_retry_controls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime_path = tmp_path / "config.json"
    runtime_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "_runtime_config_path", lambda: runtime_path)
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "65536")
    monkeypatch.setenv("LLM_LONG_OUTPUT_TIMEOUT_SECONDS", "240")
    monkeypatch.setenv("LLM_THINKING_MODE", "enabled")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "max")

    settings = config.get_settings()

    assert settings.llm_timeout_seconds == 12.5
    assert settings.llm_max_retries == 0
    assert settings.llm_max_output_tokens == 65536
    assert settings.llm_long_output_timeout_seconds == 240
    assert settings.llm_thinking_mode == "enabled"
    assert settings.llm_reasoning_effort == "max"


def test_model_provider_payload_exposes_deepseek_thinking_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("LLM_THINKING_MODE", "enabled")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "max")

    from bootstrap.settings import AppSettingsService

    payload = AppSettingsService(BACKEND_DIR).model_provider_payload()

    assert payload["thinking_mode"] == "enabled"
    assert payload["reasoning_effort"] == "max"


def test_soul_image_asset_config_uses_runtime_override() -> None:
    from soul.image_asset_service import SoulImageAssetService

    service = SoulImageAssetService(BACKEND_DIR)

    payload = service.set_config(
        base_url="https://images.example.test/v1",
        model="gpt-image-2",
        api_key="image-key",
    )

    assert payload["base_url"] == "https://images.example.test/v1"
    assert payload["model"] == "gpt-image-2"
    assert payload["api_key_present"] is True
    assert "image-key" not in str(payload)


def test_soul_image_asset_generation_reports_non_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytest

    from soul.image_asset_service import SoulImageAssetError, SoulImageAssetService

    service = SoulImageAssetService(BACKEND_DIR)
    service.set_config(
        base_url="https://images.example.test/v1",
        model="gpt-image-2",
        api_key="image-key",
    )

    class _Response:
        status_code = 200
        text = "<html>wrong endpoint</html>"
        headers = {"content-type": "text/html"}

        def json(self):
            import json

            raise json.JSONDecodeError("bad", self.text, 0)

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return _Response()

    monkeypatch.setattr("soul.image_asset_service.httpx.AsyncClient", _Client)

    with pytest.raises(SoulImageAssetError) as exc_info:
        import asyncio

        asyncio.run(service.generate(prompt="test image", target_id="non-json-test", asset_kind="chat"))

    assert "non-JSON response" in str(exc_info.value)
    assert "text/html" in str(exc_info.value)


def test_runtime_config_console_includes_soul_image_asset_group() -> None:
    from bootstrap.settings import AppSettingsService

    payload = AppSettingsService(BACKEND_DIR).runtime_config_console_payload()
    image_group = next(group for group in payload["groups"] if group["group_id"] == "soul_image_assets")
    field_map = {field["key"]: field for field in image_group["fields"]}

    assert image_group["title"] == "生图模型"
    assert field_map["base_url"]["type"] == "text"
    assert field_map["model"]["value"] == "gpt-image-2"
    assert field_map["api_key"]["type"] == "secret"
    assert "api_key" not in str(field_map["api_key"].get("value", ""))


def test_runtime_config_console_saves_soul_image_asset_group() -> None:
    from bootstrap.settings import AppSettingsService
    from soul.image_asset_service import SoulImageAssetService

    service = AppSettingsService(BACKEND_DIR)
    payload = service.set_runtime_config_group(
        "soul_image_assets",
        {
            "base_url": "https://images.example.test/v1",
            "model": "gpt-image-2",
            "api_key": "image-key",
        },
    )
    image_group = next(group for group in payload["groups"] if group["group_id"] == "soul_image_assets")
    field_map = {field["key"]: field for field in image_group["fields"]}

    summary = SoulImageAssetService(BACKEND_DIR).config_summary()
    assert summary["base_url"] == "https://images.example.test/v1"
    assert summary["api_key_present"] is True
    assert field_map["api_key"]["configured"] is True
    assert "image-key" not in str(payload)


def test_settings_resolve_cross_provider_llm_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("LLM_API_KEY", "deepseek-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "bailian")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "qwen3.5-plus")
    monkeypatch.setenv("BAILIAN_API_KEY", "bailian-key")
    monkeypatch.setenv("BAILIAN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("BAILIAN_MODEL", "qwen3.5-plus")

    settings = config.get_settings()

    assert settings.llm_fallback_provider == "bailian"
    assert settings.llm_fallback_model == "qwen3.5-plus"
    assert settings.llm_fallback_api_key == "bailian-key"
    assert settings.llm_fallback_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_provider_specific_llm_model_takes_precedence_over_global_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("DEEPSEEK_MODEL", "DeepSeek-V4-Flash")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    settings = config.get_settings()

    assert settings.llm_provider == "deepseek"
    assert settings.llm_model == "deepseek-v4-flash"


def test_provider_specific_fallback_model_takes_precedence_over_global_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "bailian")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "glm-5")
    monkeypatch.setenv("BAILIAN_MODEL", "qwen3.5-plus")
    monkeypatch.setenv("BAILIAN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    settings = config.get_settings()

    assert settings.llm_fallback_provider == "bailian"
    assert settings.llm_fallback_model == "qwen3.5-plus"


def test_runtime_override_exposes_llm_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime_path = tmp_path / "config.json"
    runtime_path.write_text(
        """
{
  "model_provider": {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com",
    "api_key": "primary-key",
    "fallback_provider": "bailian",
    "fallback_model": "qwen3.5-plus",
    "fallback_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "fallback_api_key": "fallback-key"
  }
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "_runtime_config_path", lambda: runtime_path)

    settings = config.get_settings()

    assert settings.llm_provider == "deepseek"
    assert settings.llm_api_key == "primary-key"
    assert settings.llm_fallback_provider == "bailian"
    assert settings.llm_fallback_model == "qwen3.5-plus"
    assert settings.llm_fallback_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert settings.llm_fallback_api_key == "fallback-key"


def test_runtime_override_corrects_fallback_provider_from_model_and_base_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_path = tmp_path / "config.json"
    runtime_path.write_text(
        """
{
  "model_provider": {
    "provider": "deepseek",
    "model": "deepseek-v4-pro",
    "base_url": "https://api.deepseek.com/v1",
    "fallback_provider": "openai",
    "fallback_model": "deepseek-v4-flash",
    "fallback_base_url": "https://api.deepseek.com/v1"
  }
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "_runtime_config_path", lambda: runtime_path)

    settings = config.get_settings()

    assert settings.llm_fallback_provider == "deepseek"
    assert settings.llm_fallback_model == "deepseek-v4-flash"
    assert settings.llm_fallback_base_url == "https://api.deepseek.com/v1"


def test_runtime_system_config_overrides_static_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime_path = tmp_path / "config.json"
    runtime_path.write_text(
        """
{
  "system_config": {
    "embedding": {
      "provider": "openai",
      "model": "text-embedding-3-large",
      "base_url": "https://example.test/v1",
      "dimensions": 3072,
      "api_key": "runtime-embedding-key"
    },
    "retrieval": {
      "vector_store_backend": "faiss",
      "retrieval_core_backend": "legacy",
      "rerank_enabled": true,
      "rerank_top_n": 12
    },
    "runtime": {
      "llm_timeout_seconds": 300,
      "llm_max_retries": 4,
      "terminal_timeout_seconds": 300
    }
  }
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "_runtime_config_path", lambda: runtime_path)

    settings = config.get_settings()

    assert settings.embedding_provider == "openai"
    assert settings.embedding_model == "text-embedding-3-large"
    assert settings.embedding_base_url == "https://example.test/v1"
    assert settings.embedding_dimensions == 3072
    assert settings.embedding_api_key == "runtime-embedding-key"
    assert settings.vector_store_backend == "qdrant"
    assert settings.retrieval_core_backend == "llamaindex"
    assert settings.rerank_enabled is True
    assert settings.rerank_top_n == 12
    assert settings.llm_timeout_seconds == 300
    assert settings.llm_max_retries == 4
    assert settings.terminal_timeout_seconds == 300


def test_rerank_top_n_default_is_cost_governed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime_path = tmp_path / "config.json"
    runtime_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "_runtime_config_path", lambda: runtime_path)
    monkeypatch.delenv("RERANK_TOP_N", raising=False)

    settings = config.get_settings()

    assert settings.rerank_top_n == 50


def test_runtime_system_config_exposes_long_output_controls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime_path = tmp_path / "config.json"
    runtime_path.write_text(
        """
{
  "system_config": {
    "runtime": {
      "llm_max_output_tokens": 65536,
      "llm_long_output_timeout_seconds": 360,
      "llm_thinking_mode": "disabled",
      "llm_reasoning_effort": "high"
    }
  }
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "_runtime_config_path", lambda: runtime_path)

    settings = config.get_settings()

    assert settings.llm_max_output_tokens == 65536
    assert settings.llm_long_output_timeout_seconds == 360
    assert settings.llm_thinking_mode == "disabled"
    assert settings.llm_reasoning_effort == "high"


def test_runtime_config_console_includes_long_output_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from bootstrap.settings import AppSettingsService

    runtime_path = tmp_path / "config.json"
    runtime_path.write_text(
        """
{
  "system_config": {
    "runtime": {
      "llm_max_output_tokens": 65536,
      "llm_long_output_timeout_seconds": 360,
      "llm_thinking_mode": "disabled",
      "llm_reasoning_effort": "high"
    }
  }
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "_runtime_config_path", lambda: runtime_path)
    monkeypatch.setattr(config.runtime_config, "_config_path", runtime_path)

    payload = AppSettingsService(BACKEND_DIR).runtime_config_console_payload()
    runtime_group = next(group for group in payload["groups"] if group["group_id"] == "runtime")
    field_map = {field["key"]: field for field in runtime_group["fields"]}

    assert runtime_group["title"] == "运行限制与长输出"
    assert field_map["llm_max_output_tokens"]["value"] == 65536
    assert field_map["llm_long_output_timeout_seconds"]["value"] == 360
    assert field_map["llm_thinking_mode"]["options"] == ["disabled", "enabled"]
    assert field_map["llm_reasoning_effort"]["options"] == ["high", "max"]


def test_repo_default_runtime_config_prefers_deepseek_pro_long_output_defaults() -> None:
    import json

    payload = json.loads((BACKEND_DIR / "config.json").read_text(encoding="utf-8"))

    assert payload["model_provider"]["provider"] == "deepseek"
    assert payload["model_provider"]["model"] == "deepseek-v4-pro"
    assert payload["model_provider"]["base_url"] == "https://api.deepseek.com/v1"

    runtime = payload["system_config"]["runtime"]
    assert runtime["llm_max_output_tokens"] == 65536
    assert runtime["llm_long_output_timeout_seconds"] == 360.0
    assert runtime["llm_thinking_mode"] == "enabled"
    assert runtime["llm_reasoning_effort"] == "high"


