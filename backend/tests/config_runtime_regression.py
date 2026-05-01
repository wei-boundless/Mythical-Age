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
    assert settings.vector_store_backend == "faiss"
    assert settings.retrieval_core_backend == "legacy"
    assert settings.rerank_enabled is True
    assert settings.rerank_top_n == 12
    assert settings.llm_timeout_seconds == 300
    assert settings.llm_max_retries == 4
    assert settings.terminal_timeout_seconds == 300
