from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_settings_expose_llm_timeout_and_retry_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")

    settings = config.get_settings()

    assert settings.llm_timeout_seconds == 12.5
    assert settings.llm_max_retries == 0


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
