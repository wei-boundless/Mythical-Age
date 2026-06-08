from __future__ import annotations

import asyncio
import inspect
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from context_system.compaction.semantic_worker import (
    CONTEXT_COMPACTOR_AGENT_ID,
    SemanticCompactionWorkerResult,
    semantic_compactor_registration_from_worker,
)
from runtime.model_gateway.model_response_protocol import model_response_protocol_from_response

from .assembly import assemble_runtime
from .compiler import RuntimeCompiler


@dataclass(slots=True)
class RegisteredSemanticCompactionWorker:
    """Runtime adapter for the registered context compactor profile."""

    base_dir: Path
    model_runtime: Any
    agent_runtime_profile: Any
    compiler: RuntimeCompiler
    model_selection: dict[str, Any]
    task_environment_id: str = "env.general.workspace"
    permission_mode: str = "default"
    registration: dict[str, Any] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.base_dir = Path(self.base_dir)
        self.model_selection = dict(self.model_selection or {})
        self.registration = _semantic_compactor_registration_from_profile(self.agent_runtime_profile)
        semantic_compactor_registration_from_worker(self)

    def compact(self, request: Any) -> SemanticCompactionWorkerResult:
        request_payload = request.to_dict() if hasattr(request, "to_dict") else dict(request or {})
        request_id = str(request_payload.get("request_id") or "context_compaction:semantic")
        diagnostics = dict(request_payload.get("diagnostics") or {})
        session_id = str(diagnostics.get("session_id") or "semantic_compaction")
        turn_id = str(diagnostics.get("turn_id") or "")
        task_run_id = str(diagnostics.get("task_run_id") or "")
        task_environment_id = (
            str(diagnostics.get("task_environment_id") or "").strip()
            or self.task_environment_id
            or "env.general.workspace"
        )
        try:
            runtime_assembly = assemble_runtime(
                backend_dir=self.base_dir,
                session_id=session_id,
                turn_id=turn_id or f"semantic_compaction:{request_id}",
                agent_invocation_id=f"aginvoke:{request_id}:semantic_compaction",
                request_task_selection={"task_environment_id": task_environment_id},
                model_selection=self.model_selection,
                agent_runtime_profile=self.agent_runtime_profile,
                tool_instances=(),
                definitions_by_name={},
                permission_mode=self.permission_mode,
            )
            compilation = self.compiler.compile_semantic_compaction_packet(
                semantic_request=request,
                runtime_assembly=runtime_assembly,
                agent_runtime_profile=self.agent_runtime_profile,
                session_id=session_id,
                turn_id=turn_id,
                task_run_id=task_run_id,
                model_selection=self.model_selection,
            )
            response = _call_model_runtime_sync(
                self.model_runtime,
                compilation.packet.model_messages,
                model_selection=self.model_selection,
                accounting_context={
                    "request_id": request_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "task_run_id": task_run_id,
                    "source": "harness.runtime.semantic_compaction_adapter",
                    "prompt_manifest": dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                    "segment_plan": dict(compilation.packet.segment_plan or {}),
                    "cache_metric_scope": "semantic_compaction_worker",
                },
            )
        except Exception as exc:
            return SemanticCompactionWorkerResult(
                ok=False,
                diagnostics={
                    "reason": "semantic_compaction_runtime_adapter_failed",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                    "request_id": request_id,
                },
            )

        return _semantic_compaction_result_from_response(
            response,
            request_id=request_id,
            packet_ref=str(compilation.packet.packet_id),
        )


def build_registered_semantic_compaction_worker(
    *,
    base_dir: Path,
    model_runtime: Any,
    agent_runtime_profile_resolver: Any | None = None,
    compiler: RuntimeCompiler | None = None,
    model_selection: dict[str, Any] | None = None,
    task_environment_id: str = "env.general.workspace",
    permission_mode: str = "default",
) -> RegisteredSemanticCompactionWorker | None:
    if model_runtime is None:
        return None
    resolver = agent_runtime_profile_resolver or AgentRuntimeRegistry(Path(base_dir)).get_profile
    profile = resolver(CONTEXT_COMPACTOR_AGENT_ID) if callable(resolver) else None
    if profile is None:
        return None
    resolved_model_selection = {
        **_model_selection_from_profile(profile),
        **dict(model_selection or {}),
    }
    return RegisteredSemanticCompactionWorker(
        base_dir=Path(base_dir),
        model_runtime=model_runtime,
        agent_runtime_profile=profile,
        compiler=compiler or RuntimeCompiler(base_dir=Path(base_dir)),
        model_selection=resolved_model_selection,
        task_environment_id=task_environment_id,
        permission_mode=permission_mode,
    )


def _semantic_compactor_registration_from_profile(profile: Any) -> dict[str, Any]:
    metadata = dict(getattr(profile, "metadata", {}) or {})
    runtime_config = dict(metadata.get("runtime_config") or {})
    subagent_policy = getattr(profile, "subagent_policy", None)
    return {
        "agent_id": str(getattr(profile, "agent_id", "") or ""),
        "agent_profile_id": str(getattr(profile, "agent_profile_id", "") or ""),
        "runtime_template_id": str(runtime_config.get("template_id") or metadata.get("runtime_template_id") or ""),
        "runtime_kind": str(runtime_config.get("runtime_kind") or ""),
        "allowed_operations": [str(item) for item in tuple(getattr(profile, "allowed_operations", ()) or ())],
        "blocked_operations": [str(item) for item in tuple(getattr(profile, "blocked_operations", ()) or ())],
        "allow_nested_subagents": bool(getattr(subagent_policy, "allow_nested_subagents", False)),
    }


def _model_selection_from_profile(profile: Any) -> dict[str, Any]:
    model_profile = getattr(profile, "model_profile", None)
    if model_profile is None:
        return {}
    if hasattr(model_profile, "to_dict"):
        payload = model_profile.to_dict()
    elif isinstance(model_profile, dict):
        payload = dict(model_profile)
    else:
        return {}
    return {
        str(key): value
        for key, value in dict(payload or {}).items()
        if value not in (None, "", [], {})
    }


def _semantic_compaction_result_from_response(
    response: Any,
    *,
    request_id: str,
    packet_ref: str,
) -> SemanticCompactionWorkerResult:
    protocol = model_response_protocol_from_response(
        response,
        request_id=request_id,
        allow_native_tool_calls=False,
    )
    payload = dict(protocol.json_payload or {})
    summary = str(payload.get("summary_content") or payload.get("summary") or "").strip()
    structured_summary = _structured_summary_from_payload(payload)
    diagnostics = {
        "request_id": request_id,
        "packet_ref": packet_ref,
        "model_response_protocol": protocol.to_dict(),
        **(dict(payload.get("diagnostics") or {}) if isinstance(payload.get("diagnostics"), dict) else {}),
    }
    if protocol.protocol_errors:
        return SemanticCompactionWorkerResult(
            ok=False,
            diagnostics={**diagnostics, "reason": "semantic_compactor_protocol_error"},
        )
    if not payload:
        return SemanticCompactionWorkerResult(
            ok=False,
            diagnostics={**diagnostics, "reason": "semantic_compactor_json_required"},
        )
    if not summary and not structured_summary:
        return SemanticCompactionWorkerResult(
            ok=False,
            diagnostics={**diagnostics, "reason": "semantic_compactor_empty_recovery_package"},
        )
    return SemanticCompactionWorkerResult(
        ok=True,
        summary_content=summary,
        structured_summary=structured_summary,
        source="registered_semantic_compactor",
        diagnostics=diagnostics,
    )


def _structured_summary_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("structured_summary", "recovery_package", "checkpoint"):
        value = payload.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _call_model_runtime_sync(
    model_runtime: Any,
    messages: list[Any],
    *,
    model_selection: dict[str, Any],
    accounting_context: dict[str, Any],
) -> Any:
    invoker = getattr(model_runtime, "invoke_messages", None)
    if not callable(invoker):
        raise RuntimeError("model_runtime.invoke_messages is unavailable")
    kwargs: dict[str, Any] = {}
    if model_selection and _callable_accepts_kwarg(invoker, "model_spec"):
        kwargs["model_spec"] = dict(model_selection)
    kwargs["accounting_context"] = dict(accounting_context)
    return _resolve_sync(invoker(messages, **kwargs))


def _callable_accepts_kwarg(callback: Any, kwarg: str) -> bool:
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return True
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return True
        if parameter.name == kwarg and parameter.kind in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }:
            return True
    return False


def _resolve_sync(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    if not loop.is_running():
        return asyncio.run(value)
    result: dict[str, Any] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(value)
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=_runner, name="semantic-compaction-worker", daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")
