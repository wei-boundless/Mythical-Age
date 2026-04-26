from __future__ import annotations

import copy
from typing import Any

from orchestration.adapters import build_shadow_orchestration_plan
from orchestration.behavior_trace import build_behavior_snapshot
from orchestration.contract_preview import build_contract_previews
from query.prompt_manifest import compact_prompt_manifest
from runtime.session_store import validate_session_id


async def build_behavior_dry_run(
    runtime: Any,
    *,
    session_id: str,
    message: str,
    ephemeral_system_messages: list[str] | None = None,
    explicit_subtasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_session_id = validate_session_id(session_id)
    normalized_message = str(message or "").strip()
    if not normalized_message:
        raise ValueError("message is required")

    history = _load_existing_history(runtime, normalized_session_id)
    query_runtime = runtime.query_runtime
    authority_context = query_runtime._load_session_authoritative_context(normalized_session_id)
    plan = query_runtime._planner_build_plan(
        session_id=normalized_session_id,
        message=normalized_message,
        history=history,
        ephemeral_system_messages=list(ephemeral_system_messages or []),
        authority_context=authority_context,
        explicit_subtasks=list(explicit_subtasks or []),
    )
    executions = plan.iter_executions()
    execution = executions[0] if executions else None
    warnings: list[str] = []
    if execution is None:
        raise ValueError("planner produced no execution")

    skill_inspection = _inspect_skill_policy(query_runtime, execution)
    context_preview = _inspect_context(runtime, normalized_session_id, execution)
    contract_previews = build_contract_previews(runtime=runtime, execution=execution)
    prompt_manifest = await _build_prompt_manifest(query_runtime, normalized_session_id, execution, warnings)
    orchestration_plan = build_shadow_orchestration_plan(
        session_id=normalized_session_id,
        message=normalized_message,
        query_plan=plan,
        source="dry-run",
        mode=_orchestration_mode(runtime),
        warnings=warnings,
        contract_previews=contract_previews,
    ).to_dict()

    snapshot = build_behavior_snapshot(
        source="dry-run",
        session_id=normalized_session_id,
        message=normalized_message,
        plan=plan,
        execution=execution,
        orchestration_plan=orchestration_plan,
        skill_inspection=skill_inspection,
        context_preview=context_preview,
        prompt_manifest=prompt_manifest,
        contract_previews=contract_previews,
        warnings=warnings,
    )
    snapshot["dry_run"] = {
        "side_effects": {
            "model_called": False,
            "tools_executed": False,
            "session_written": False,
            "memory_written": False,
        },
        "execution_count": len(executions),
    }
    return snapshot


def _orchestration_mode(runtime: Any) -> str:
    settings = getattr(runtime, "settings", None)
    getter = getattr(settings, "get_orchestration_plan_mode", None)
    if callable(getter):
        mode = str(getter() or "shadow").strip().lower()
        return mode if mode != "legacy" else "shadow"
    return "shadow"


def _load_existing_history(runtime: Any, session_id: str) -> list[dict[str, Any]]:
    path = runtime.session_manager._session_path(session_id)
    if not path.exists():
        raise ValueError(f"session does not exist: {session_id}")
    record = runtime.session_manager.load_session_record(session_id)
    messages = []
    for item in list(record.get("messages", []) or []):
        role = str(item.get("role", "") or "")
        content = str(item.get("content", "") or "")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    return messages


def _inspect_skill_policy(query_runtime: Any, execution: Any) -> dict[str, Any]:
    resolver = getattr(getattr(query_runtime, "planner", None), "skill_policy_resolver", None)
    if resolver is None or not hasattr(resolver, "inspect"):
        return {}
    task_frame = copy.copy(getattr(execution, "query_understanding", None))
    if task_frame is not None and getattr(task_frame, "skill_name", None):
        # The planner has already attached the final skill. Clearing the field
        # lets inspection show structural candidates instead of only echoing the
        # selected explicit name.
        task_frame.skill_name = None
    inspection = resolver.inspect(task_frame=task_frame)
    return inspection.to_dict() if hasattr(inspection, "to_dict") else {}


def _inspect_context(runtime: Any, session_id: str, execution: Any) -> dict[str, Any]:
    try:
        return runtime.memory_facade.inspect_query_context(
            session_id,
            history=list(getattr(execution, "history", []) or []),
            pending_user_message=str(getattr(execution, "message", "") or ""),
            memory_intent=getattr(execution, "memory_intent", None),
            relevant_notes=None,
            retrieval_results=[],
        )
    except Exception as exc:
        return {
            "context_management": {
                "pressure_level": "unknown",
                "strategy": "inspect_failed",
                "error": str(exc),
            },
            "session_memory": {},
            "durable_memory": {},
        }


async def _build_prompt_manifest(
    query_runtime: Any,
    session_id: str,
    execution: Any,
    warnings: list[str],
) -> dict[str, Any]:
    if str(getattr(execution, "execution_kind", "") or "") in {"direct_tool", "worker"}:
        return {}
    try:
        _prompt, manifest = await query_runtime._abuild_system_prompt_with_manifest_for_execution(
            session_id=session_id,
            execution=execution,
            retrieval_results=[],
            relevant_memory_notes=None,
        )
        return compact_prompt_manifest(manifest)
    except Exception as exc:
        warnings.append(f"prompt_manifest_preview_failed: {exc}")
        return {}
