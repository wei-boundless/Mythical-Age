from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
HEAVY_MODULE_PREFIXES = (
    "cv2",
    "docling",
    "langchain.agents",
    "langchain_deepseek",
    "langchain_openai",
    "onnxruntime",
    "paddle",
    "rapidocr",
    "sentence_transformers",
    "torch",
    "transformers",
)

MODEL_GATEWAY_HEAVY_MODULE_PREFIXES = (
    *HEAVY_MODULE_PREFIXES,
    "langchain_core",
)


def _heavy_modules_after(script: str) -> list[str]:
    probe = f"""
import json
import sys
from pathlib import Path

sys.path.insert(0, {str(BACKEND_DIR)!r})

{textwrap.dedent(script)}

prefixes = {HEAVY_MODULE_PREFIXES!r}
loaded = sorted(
    name for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)
)
print(json.dumps(loaded))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    return list(json.loads(result.stdout.strip() or "[]"))


def _modules_after(script: str, prefixes: tuple[str, ...]) -> list[str]:
    probe = f"""
import json
import sys
from pathlib import Path

sys.path.insert(0, {str(BACKEND_DIR)!r})

{textwrap.dedent(script)}

prefixes = {prefixes!r}
loaded = sorted(
    name for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)
)
print(json.dumps(loaded))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    return list(json.loads(result.stdout.strip() or "[]"))


def test_evidence_import_boundary_does_not_load_local_ml_stack() -> None:
    loaded = _heavy_modules_after(
        """
import evidence
from evidence.models import EvidenceEnvelope
from evidence.orchestrator import EvidenceOrchestrator
"""
    )

    assert loaded == []


def test_app_runtime_startup_boundary_does_not_load_provider_or_local_ml_stack() -> None:
    loaded = _heavy_modules_after(
        """
from pathlib import Path

from bootstrap.app_runtime import AppRuntime

runtime = AppRuntime()
runtime.initialize(Path.cwd())
"""
    )

    assert loaded == []


def test_local_mcp_catalog_boundary_does_not_load_worker_ml_stack() -> None:
    loaded = _heavy_modules_after(
        """
from pathlib import Path

from capability_system.mcp.management_service import MCPManagementService
from capability_system.mcp.server.local_capability_server import LocalCapabilityMCPExecutor

service = MCPManagementService(Path.cwd())
service.build_catalog()
LocalCapabilityMCPExecutor(backend_dir=Path.cwd())
"""
    )

    assert loaded == []


def test_model_runtime_chat_model_boundary_does_not_load_langchain_or_local_ml_stack() -> None:
    loaded = _modules_after(
        """
from types import SimpleNamespace

from runtime.model_gateway.model_runtime import ModelRuntime, ModelSpec

settings = SimpleNamespace(
    static=SimpleNamespace(
        llm_timeout_seconds=1.0,
        llm_long_output_timeout_seconds=1.0,
        llm_max_retries=0,
        llm_max_output_tokens=64,
        llm_thinking_mode="disabled",
        llm_reasoning_effort="",
    )
)
runtime = ModelRuntime(settings)
runtime._build_chat_model_for_spec(
    ModelSpec(
        provider="deepseek",
        model="deepseek-v4-flash",
        api_key="test-key",
        base_url="https://api.deepseek.com",
        max_output_tokens=64,
        timeout_seconds=1.0,
        long_output_timeout_seconds=1.0,
        max_retries=0,
        thinking_mode="disabled",
        reasoning_effort="",
    )
)
""",
        MODEL_GATEWAY_HEAVY_MODULE_PREFIXES,
    )

    assert loaded == []
