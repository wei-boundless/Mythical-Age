from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config


def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    env_names = {name for name in os.environ if name.startswith("LLM_")}
    env_names.update(config.LLM_PROVIDER_MODEL_ENVS.values())
    env_names.update(config.LLM_PROVIDER_BASE_URL_ENVS.values())
    for defaults in config.LLM_PROVIDER_DEFAULTS.values():
        env_names.update(str(name) for name in defaults.get("credential_envs") or ())
    env_names.update(
        {
            "LLM_PROVIDER",
            "LLM_FALLBACK_PROVIDER",
            "LLM_FALLBACK_MODEL",
            "LLM_FALLBACK_BASE_URL",
            "LLM_FALLBACK_API_KEY",
        }
    )
    for name in env_names:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _isolated_runtime_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _clear_llm_env(monkeypatch)
    runtime_path = tmp_path / "config.json"
    runtime_path.write_text("{}", encoding="utf-8")
    isolated_manager = config.RuntimeConfigManager(runtime_path)
    monkeypatch.setattr(config, "_runtime_config_path", lambda: runtime_path)
    monkeypatch.setattr(config, "runtime_config", isolated_manager)
    monkeypatch.setattr(config, "_load_env_file", lambda: BACKEND_DIR)
    loaded_image_asset_module = sys.modules.get("capability_system.capabilities.image_generation.image_asset_service")
    if loaded_image_asset_module is not None:
        monkeypatch.setattr(loaded_image_asset_module, "runtime_config", isolated_manager)
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


def test_llm_provider_resolution_tables_cover_all_catalog_providers() -> None:
    providers = set(config.LLM_PROVIDER_DEFAULTS)

    assert set(config.LLM_PROVIDER_MODEL_ENVS) == providers
    assert set(config.LLM_PROVIDER_BASE_URL_ENVS) == providers
    assert all(config.LLM_PROVIDER_DEFAULTS[provider].get("credential_envs") is not None for provider in providers)


def test_provider_specific_primary_envs_precede_global_compatibility_envs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_MODEL", "DeepSeek-V4-Flash")
    monkeypatch.setenv("LLM_MODEL", "global-model")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/provider")
    monkeypatch.setenv("LLM_BASE_URL", "https://global.example.test/v1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "provider-key")
    monkeypatch.setenv("LLM_API_KEY", "global-key")

    settings = config.get_settings()

    assert settings.llm_model == "deepseek-v4-flash"
    assert settings.llm_base_url == "https://api.deepseek.com/provider"
    assert settings.llm_api_key == "provider-key"


def test_global_llm_api_key_remains_primary_compatibility_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_API_KEY", "global-key")

    settings = config.get_settings()

    assert settings.llm_provider == "anthropic"
    assert settings.llm_api_key == "global-key"


def test_fallback_api_key_does_not_leak_primary_global_llm_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_API_KEY", "primary-global-key")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "openrouter")

    settings = config.get_settings()

    assert settings.llm_fallback_provider == "openrouter"
    assert settings.llm_fallback_api_key is None


def test_runtime_payload_warns_on_invalid_runtime_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime_path = tmp_path / "config.json"
    runtime_path.write_text("{ broken", encoding="utf-8")
    monkeypatch.setattr(config, "_runtime_config_path", lambda: runtime_path)
    config._RUNTIME_CONFIG_WARNING_KEYS.clear()
    caplog.set_level(logging.WARNING, logger=config.__name__)

    assert config._runtime_payload() == {}

    messages = [record.message for record in caplog.records]
    assert any("Ignoring runtime config" in message and "invalid JSON" in message for message in messages)


def test_runtime_config_manager_warns_and_recovers_invalid_runtime_json(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime_path = tmp_path / "config.json"
    runtime_path.write_text("{ broken", encoding="utf-8")
    manager = config.RuntimeConfigManager(runtime_path)
    config._RUNTIME_CONFIG_WARNING_KEYS.clear()
    caplog.set_level(logging.WARNING, logger=config.__name__)

    payload = manager.load()

    assert payload["rag_mode"] is False
    assert payload["permission_mode"] == "default"
    assert payload["orchestration_plan_mode"] == "primary"
    assert payload["context_budget_preset"] == "deepseek_1m"
    assert json.loads(runtime_path.read_text(encoding="utf-8")) == payload
    messages = [record.message for record in caplog.records]
    assert any("Ignoring runtime config" in message and "invalid JSON" in message for message in messages)


def test_fallback_provider_uses_model_hint_to_avoid_cross_provider_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "deepseek-v4-flash")

    settings = config.get_settings()

    assert settings.llm_fallback_provider == "deepseek"
    assert settings.llm_fallback_model == "deepseek-v4-flash"
    assert settings.llm_fallback_base_url == "https://api.deepseek.com"


def test_runtime_permission_mode_is_normalized_on_read_and_write() -> None:
    config.runtime_config.set_permission_mode("dangerous_bypass")
    assert config.runtime_config.get_permission_mode() == "default"
    assert config.runtime_config.load()["permission_mode"] == "default"

    config.runtime_config.set_permission_mode(" FULL_ACCESS ")
    assert config.runtime_config.get_permission_mode() == "full_access"
    assert config.runtime_config.load()["permission_mode"] == "full_access"


def test_image_asset_config_uses_env_before_runtime_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from capability_system.capabilities.image_generation.image_asset_service import ImageAssetService

    service = ImageAssetService(BACKEND_DIR)

    service.set_config(
        base_url="https://images.example.test/v1",
        model="gpt-image-2",
        api_key="image-key",
    )
    monkeypatch.setenv("IMAGE_API_BASE_URL", "https://www.aimapi.cloud/v1")
    monkeypatch.setenv("IMAGE_API_KEY", "env-image-key")
    monkeypatch.setenv("IMAGE_MODEL", "env-image-model")

    payload = service.config_summary()

    assert payload["base_url"] == "https://www.aimapi.cloud/v1"
    assert payload["model"] == "env-image-model"
    assert payload["api_key_present"] is True
    assert "env-image-key" not in str(payload)


def test_image_asset_generation_reports_non_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytest

    from capability_system.capabilities.image_generation.image_asset_service import ImageAssetError, ImageAssetService

    service = ImageAssetService(BACKEND_DIR)
    monkeypatch.setenv("IMAGE_API_BASE_URL", "https://images.example.test/v1")
    monkeypatch.setenv("IMAGE_MODEL", "image-2")
    monkeypatch.setenv("IMAGE_API_KEY", "image-key")

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

    monkeypatch.setattr("capability_system.capabilities.image_generation.image_asset_service.httpx.AsyncClient", _Client)

    with pytest.raises(ImageAssetError) as exc_info:
        import asyncio

        asyncio.run(service.generate(prompt="test image", target_id="non-json-test", asset_kind="chat"))

    assert "non-JSON response" in str(exc_info.value)
    assert "text/html" in str(exc_info.value)


def test_image_asset_generation_falls_back_on_model_endpoint_incompatibility(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64
    import asyncio
    import io
    import json

    from PIL import Image
    from capability_system.capabilities.image_generation.image_asset_service import ImageAssetService

    service = ImageAssetService(BACKEND_DIR)
    monkeypatch.setenv("IMAGE_API_BASE_URL", "https://images.example.test/v1")
    monkeypatch.setenv("IMAGE_MODEL", "image-2")
    monkeypatch.setenv("IMAGE_API_KEY", "image-key")
    monkeypatch.setenv("IMAGE_FALLBACK_MODELS", "image-2-compatible")
    png_buffer = io.BytesIO()
    Image.new("RGBA", (1024, 1024), (20, 30, 40, 255)).save(png_buffer, format="PNG")
    png = png_buffer.getvalue()
    calls: list[dict[str, object]] = []

    class _Response:
        def __init__(self, status_code: int, payload: dict[str, object]) -> None:
            self.status_code = status_code
            self._payload = payload
            self.text = json.dumps(payload)
            self.headers = {"content-type": "application/json"}

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, _endpoint, headers=None, json=None):
            calls.append(dict(json or {}))
            if json.get("model") == "image-2":
                return _Response(
                    400,
                    {"error": {"message": "Tool choice 'image_generation' not found in 'tools' parameter.", "type": "invalid_request_error"}},
                )
            return _Response(200, {"data": [{"b64_json": base64.b64encode(png).decode("ascii")}], "created": 1})

    monkeypatch.setattr("capability_system.capabilities.image_generation.image_asset_service.httpx.AsyncClient", _Client)

    generated = asyncio.run(service.generate(prompt="test image", target_id="fallback-test", asset_kind="chat", overwrite=True))

    assert generated["bytes"] == len(png)
    assert [call["model"] for call in calls[:2]] == ["image-2"] * 2
    assert calls[2]["model"] == "image-2-compatible"
    assert "response_format" not in calls[0]
    assert calls[1]["response_format"] == "b64_json"


def test_image_asset_generation_resizes_small_requested_size_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import base64
    import io
    import json

    from PIL import Image
    from capability_system.capabilities.image_generation.image_asset_service import ImageAssetService

    service = ImageAssetService(BACKEND_DIR)
    monkeypatch.setenv("IMAGE_API_BASE_URL", "https://images.example.test/v1")
    monkeypatch.setenv("IMAGE_MODEL", "gpt-image-2")
    monkeypatch.setenv("IMAGE_API_KEY", "image-key")
    source = io.BytesIO()
    Image.new("RGBA", (1024, 1024), (10, 20, 30, 255)).save(source, format="PNG")
    calls: list[dict[str, object]] = []

    class _Response:
        status_code = 200
        text = "{}"
        headers = {"content-type": "application/json"}

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(source.getvalue()).decode("ascii")}], "created": 1}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, _endpoint, headers=None, json=None):
            calls.append(dict(json or {}))
            return _Response()

    monkeypatch.setattr("capability_system.capabilities.image_generation.image_asset_service.httpx.AsyncClient", _Client)

    generated = asyncio.run(
        service.generate(
            prompt="small sprite",
            target_id="resize-small-test",
            asset_kind="chat",
            size="128x128",
            overwrite=True,
        )
    )

    assert calls[0]["size"] == "1024x1024"
    assert generated["requested_size"] == "128x128"
    assert generated["provider_size"] == "1024x1024"
    assert generated["final_size"] == "128x128"
    assert generated["asset_path"].startswith("/api/image-assets/files/")
    assert generated["path"].startswith("storage/generated/images/")
    assert generated["project_path"] == generated["path"]
    assert generated["absolute_path"] == generated["file_path"]
    assert generated["storage_authority"] == "image_asset_store"
    assert generated["bypass_sandbox_publish"] is True
    with Image.open(generated["file_path"]) as image:
        assert image.size == (128, 128)


def test_image_asset_generation_uses_output_size_for_local_resize(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import base64
    import io

    from PIL import Image
    from capability_system.capabilities.image_generation.image_asset_service import ImageAssetService

    service = ImageAssetService(BACKEND_DIR)
    monkeypatch.setenv("IMAGE_API_BASE_URL", "https://images.example.test/v1")
    monkeypatch.setenv("IMAGE_MODEL", "gpt-image-2")
    monkeypatch.setenv("IMAGE_API_KEY", "image-key")
    monkeypatch.setenv("IMAGE_CONCURRENCY", "1")
    source = io.BytesIO()
    Image.new("RGBA", (1024, 1024), (40, 50, 60, 255)).save(source, format="PNG")
    calls: list[dict[str, object]] = []

    class _Response:
        status_code = 200
        text = "{}"
        headers = {"content-type": "application/json"}

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(source.getvalue()).decode("ascii")}], "created": 1}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, _endpoint, headers=None, json=None):
            calls.append(dict(json or {}))
            return _Response()

    monkeypatch.setattr("capability_system.capabilities.image_generation.image_asset_service.httpx.AsyncClient", _Client)

    generated = asyncio.run(
        service.generate(
            prompt="small sprite",
            target_id="output-size-test",
            asset_kind="chat",
            size="1024x1024",
            quality="low",
            output_size="128x128",
            overwrite=True,
        )
    )

    assert calls[0]["size"] == "1024x1024"
    assert calls[0]["quality"] == "low"
    assert generated["requested_size"] == "128x128"
    assert generated["provider_size"] == "1024x1024"
    assert generated["final_size"] == "128x128"


def test_image_asset_generation_retries_transient_gateway_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import pytest

    from capability_system.capabilities.image_generation.image_asset_service import ImageAssetError, ImageAssetService

    service = ImageAssetService(BACKEND_DIR)
    monkeypatch.setenv("IMAGE_API_BASE_URL", "https://images.example.test/v1")
    monkeypatch.setenv("IMAGE_MODEL", "image-2")
    monkeypatch.setenv("IMAGE_API_KEY", "image-key")
    calls: list[dict[str, object]] = []

    class _Response:
        status_code = 504
        text = "<html>timeout</html>"
        headers = {"content-type": "text/html"}

        def json(self):
            raise json.JSONDecodeError("bad", self.text, 0)

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            calls.append(dict(kwargs.get("json") or {}))
            return _Response()

    monkeypatch.setattr("capability_system.capabilities.image_generation.image_asset_service.httpx.AsyncClient", _Client)

    with pytest.raises(ImageAssetError) as exc_info:
        asyncio.run(service.generate(prompt="test image", target_id="failure-test", asset_kind="chat", overwrite=True))

    error = exc_info.value.to_dict()
    assert error["code"] == "image_provider_transient_error"
    assert error["retryable"] is True
    assert len(error["attempts"]) == 2
    assert error["attempts"][0]["code"] == "image_provider_transient_error"
    assert error["attempts"][1]["attempt_index"] == 2
    assert len(calls) == 2
    assert "response_format" not in calls[0]


def test_image_asset_generation_recovers_after_transient_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import base64
    import io
    import json

    from PIL import Image
    from capability_system.capabilities.image_generation.image_asset_service import ImageAssetService

    service = ImageAssetService(BACKEND_DIR)
    monkeypatch.setenv("IMAGE_API_BASE_URL", "https://images.example.test/v1")
    monkeypatch.setenv("IMAGE_MODEL", "image-2")
    monkeypatch.setenv("IMAGE_API_KEY", "image-key")
    png_buffer = io.BytesIO()
    Image.new("RGBA", (1024, 1024), (20, 30, 40, 255)).save(png_buffer, format="PNG")
    calls: list[dict[str, object]] = []

    class _Response:
        def __init__(self, status_code: int, payload: dict[str, object] | None = None, text: str = "") -> None:
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text or json.dumps(self._payload)
            self.headers = {"content-type": "application/json" if payload is not None else "text/html"}

        def json(self):
            if self.status_code >= 400:
                raise json.JSONDecodeError("bad", self.text, 0)
            return self._payload

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            calls.append(dict(kwargs.get("json") or {}))
            if len(calls) == 1:
                return _Response(504, text="<html>timeout</html>")
            return _Response(200, {"data": [{"b64_json": base64.b64encode(png_buffer.getvalue()).decode("ascii")}], "created": 1})

    monkeypatch.setattr("capability_system.capabilities.image_generation.image_asset_service.httpx.AsyncClient", _Client)

    generated = asyncio.run(service.generate(prompt="test image", target_id="retry-success-test", asset_kind="chat", overwrite=True))

    assert generated["bytes"] == len(png_buffer.getvalue())
    assert len(calls) == 2
    assert calls[0]["model"] == "image-2"
    assert calls[1]["model"] == "image-2"


def test_image_asset_generation_honors_explicit_model_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import base64
    import io

    from PIL import Image
    from capability_system.capabilities.image_generation.image_asset_service import ImageAssetService

    service = ImageAssetService(BACKEND_DIR)
    monkeypatch.setenv("IMAGE_API_BASE_URL", "https://images.example.test/v1")
    monkeypatch.setenv("IMAGE_MODEL", "env-image-model")
    monkeypatch.setenv("IMAGE_API_KEY", "image-key")
    source = io.BytesIO()
    Image.new("RGBA", (1024, 1024), (10, 20, 30, 255)).save(source, format="PNG")
    calls: list[dict[str, object]] = []
    timeouts: list[object] = []

    class _Response:
        status_code = 200
        text = "{}"
        headers = {"content-type": "application/json"}

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(source.getvalue()).decode("ascii")}], "created": 1}

    class _Client:
        def __init__(self, *args, **kwargs):
            timeouts.append(kwargs.get("timeout"))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, _endpoint, headers=None, json=None):
            calls.append(dict(json or {}))
            return _Response()

    monkeypatch.setattr("capability_system.capabilities.image_generation.image_asset_service.httpx.AsyncClient", _Client)

    generated = asyncio.run(
        service.generate(
            prompt="test image",
            target_id="explicit-model-test",
            asset_kind="chat",
            model="gpt-image-2",
            request_timeout_seconds=45,
            overwrite=True,
        )
    )

    assert calls[0]["model"] == "gpt-image-2"
    assert generated["model"] == "gpt-image-2"
    assert timeouts
    assert getattr(timeouts[0], "read", None) == 45


def test_runtime_config_console_includes_image_asset_group() -> None:
    from bootstrap.settings import AppSettingsService

    payload = AppSettingsService(BACKEND_DIR).runtime_config_console_payload()
    image_group = next(group for group in payload["groups"] if group["group_id"] == "image_assets")
    field_map = {field["key"]: field for field in image_group["fields"]}

    assert image_group["title"] == "生图模型"
    assert field_map["base_url"]["type"] == "text"
    assert field_map["model"]["value"] == "gpt-image-2"
    assert field_map["api_key"]["type"] == "secret"
    assert field_map["request_timeout_seconds"]["value"] == 150.0
    assert "api_key" not in str(field_map["api_key"].get("value", ""))


def test_runtime_config_console_saves_image_asset_group_as_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from bootstrap.settings import AppSettingsService
    from capability_system.capabilities.image_generation.image_asset_service import ImageAssetService

    monkeypatch.setenv("IMAGE_API_BASE_URL", "https://env-image.example.test/v1")
    monkeypatch.setenv("IMAGE_API_KEY", "env-image-key")
    monkeypatch.setenv("IMAGE_MODEL", "env-image-model")

    service = AppSettingsService(BACKEND_DIR)
    payload = service.set_runtime_config_group(
        "image_assets",
        {
            "base_url": "https://images.example.test/v1",
            "model": "gpt-image-2",
            "api_key": "image-key",
        },
    )
    image_group = next(group for group in payload["groups"] if group["group_id"] == "image_assets")
    field_map = {field["key"]: field for field in image_group["fields"]}

    summary = ImageAssetService(BACKEND_DIR).config_summary()
    saved = dict(config.runtime_config.load().get("image_assets") or {})
    assert saved["base_url"] == "https://images.example.test/v1"
    assert summary["base_url"] == "https://env-image.example.test/v1"
    assert summary["api_key_present"] is True
    assert field_map["api_key"]["configured"] is True
    assert "image-key" not in str(payload)
    assert "env-image-key" not in str(payload)


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
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
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
    "model": "deepseek-v4-pro",
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
      "llm_reasoning_effort": "auto"
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
    assert settings.llm_reasoning_effort == "auto"


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
      "llm_reasoning_effort": "auto"
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
    assert "llm_reasoning_effort" not in field_map


def test_repo_default_runtime_config_uses_deepseek_1m_context_with_deepseek_pro_primary() -> None:
    import json

    payload = json.loads((BACKEND_DIR / "config.json").read_text(encoding="utf-8"))

    assert payload["model_provider"]["provider"] == "deepseek"
    assert payload["model_provider"]["model"] == "deepseek-v4-pro"
    assert payload["model_provider"]["base_url"] == "https://api.deepseek.com"
    assert payload["context_budget_preset"] == "deepseek_1m"

    runtime = payload["system_config"]["runtime"]
    assert runtime["llm_max_output_tokens"] == 65536
    assert runtime["llm_long_output_timeout_seconds"] == 360.0
    assert runtime["llm_thinking_mode"] == "enabled"
    assert "llm_reasoning_effort" not in runtime



