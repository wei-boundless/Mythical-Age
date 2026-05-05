from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .action_request import RuntimeObservation


SystemPromptBuilder = Callable[..., str]


@dataclass(frozen=True, slots=True)
class RuntimeContextSnapshot:
    snapshot_id: str
    session_id: str
    task_id: str
    model_messages: tuple[dict[str, str], ...]
    history_message_count: int = 0
    pending_user_message_chars: int = 0
    system_prompt_chars: int = 0
    token_pressure: dict[str, Any] = field(default_factory=dict)
    prompt_source_report: dict[str, Any] = field(default_factory=dict)
    context_policy_ref: str = ""
    memory_runtime_view_ref: str = ""
    projection_ref: str = ""
    prompt_manifest_ref: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.runtime_context_snapshot"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.runtime_context_snapshot":
            raise ValueError("RuntimeContextSnapshot authority must be orchestration.runtime_context_snapshot")
        if not self.snapshot_id:
            raise ValueError("RuntimeContextSnapshot requires snapshot_id")
        if not self.session_id:
            raise ValueError("RuntimeContextSnapshot requires session_id")
        if not self.task_id:
            raise ValueError("RuntimeContextSnapshot requires task_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["model_messages"] = [dict(item) for item in self.model_messages]
        return payload


@dataclass(frozen=True, slots=True)
class RuntimeContextObservationRecord:
    record_id: str
    task_run_id: str
    observation_ref: str
    observation_type: str
    source: str
    needs_model_followup: bool = False
    context_update: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.runtime_context_observation_record"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.runtime_context_observation_record":
            raise ValueError(
                "RuntimeContextObservationRecord authority must be orchestration.runtime_context_observation_record"
            )
        if not self.record_id:
            raise ValueError("RuntimeContextObservationRecord requires record_id")
        if not self.task_run_id:
            raise ValueError("RuntimeContextObservationRecord requires task_run_id")
        if not self.observation_ref:
            raise ValueError("RuntimeContextObservationRecord requires observation_ref")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RuntimeContextInvariantReport:
    report_id: str
    snapshot_ref: str
    tool_result_pairing_ok: bool = True
    needs_compaction: bool = False
    compaction_reason: str = ""
    token_pressure: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.runtime_context_invariant_report"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.runtime_context_invariant_report":
            raise ValueError(
                "RuntimeContextInvariantReport authority must be orchestration.runtime_context_invariant_report"
            )
        if not self.report_id:
            raise ValueError("RuntimeContextInvariantReport requires report_id")
        if not self.snapshot_ref:
            raise ValueError("RuntimeContextInvariantReport requires snapshot_ref")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeContextManager:
    """Builds model-visible context for the single-agent loop."""

    def __init__(self, system_prompt_builder: SystemPromptBuilder) -> None:
        self.system_prompt_builder = system_prompt_builder

    def prepare_model_context(
        self,
        *,
        session_id: str,
        task_id: str,
        user_message: str,
        history: list[dict[str, Any]],
        memory_intent: Any | None = None,
        memory_runtime_view: dict[str, Any] | None = None,
        context_policy_result: dict[str, Any] | None = None,
        stage_projection_snapshot: Any | None = None,
        runtime_execution_facts: dict[str, Any] | None = None,
    ) -> RuntimeContextSnapshot:
        system_prompt = self.system_prompt_builder(
            session_id=session_id,
            pending_user_message=user_message,
            memory_intent=memory_intent,
        )
        normalized_history = tuple(_normalize_history(history))
        pending = str(user_message or "")
        context_policy_ref = _context_policy_ref(context_policy_result)
        memory_view_ref = str((memory_runtime_view or {}).get("view_id") or "")
        projection_ref = str(getattr(stage_projection_snapshot, "projection_ref", "") or "")
        prompt_manifest_ref = str(getattr(stage_projection_snapshot, "prompt_manifest_ref", "") or "")
        runtime_prompt = _build_runtime_system_prompt(
            legacy_system_prompt=system_prompt,
            stage_projection_snapshot=stage_projection_snapshot,
            context_policy_result=context_policy_result,
            runtime_execution_facts=runtime_execution_facts,
        )
        model_messages = (
            {"role": "system", "content": runtime_prompt},
            *normalized_history,
            {"role": "user", "content": pending},
        )
        snapshot_id = _snapshot_id(
            session_id=session_id,
            task_id=task_id,
            system_prompt=runtime_prompt,
            history=normalized_history,
            pending=pending,
            context_policy_ref=context_policy_ref,
            memory_view_ref=memory_view_ref,
            projection_ref=projection_ref,
            prompt_manifest_ref=prompt_manifest_ref,
        )
        return RuntimeContextSnapshot(
            snapshot_id=snapshot_id,
            session_id=session_id,
            task_id=task_id,
            model_messages=model_messages,
            history_message_count=len(normalized_history),
            pending_user_message_chars=len(pending),
            system_prompt_chars=len(runtime_prompt),
            token_pressure=_token_pressure(context_policy_result),
            prompt_source_report=_prompt_source_report(
                stage_projection_snapshot=stage_projection_snapshot,
                context_policy_result=context_policy_result,
                legacy_system_prompt_chars=len(system_prompt),
                runtime_system_prompt_chars=len(runtime_prompt),
            ),
            context_policy_ref=context_policy_ref,
            memory_runtime_view_ref=memory_view_ref,
            projection_ref=projection_ref,
            prompt_manifest_ref=prompt_manifest_ref,
            diagnostics={
                "context_owner": "RuntimeContextManager",
                "model_message_count": len(model_messages),
                "compression_applied": False,
                "tool_result_pairing_checked": False,
                "stage_projection_consumed": bool(stage_projection_snapshot is not None),
                "prompt_manifest_bound": bool(prompt_manifest_ref),
                "prompt_source_report_built": True,
                "runtime_prompt_assembly_applied": True,
            },
        )

    def record_observation(self, observation: RuntimeObservation) -> RuntimeContextObservationRecord:
        """Normalize an observation into a future context update.

        The current single-agent lane does not mutate model_messages after the
        final answer. This record is the durable slot that tool_result and
        worker_result observations will use before a next_turn model call.
        """

        context_update = {
            "mode": "no_followup_required" if not observation.needs_model_followup else "append_for_next_turn",
            "content_chars": observation.content_chars,
            "observation_type": observation.observation_type,
        }
        return RuntimeContextObservationRecord(
            record_id=f"ctxobs:{observation.observation_id}",
            task_run_id=observation.task_run_id,
            observation_ref=observation.observation_id,
            observation_type=observation.observation_type,
            source=observation.source,
            needs_model_followup=observation.needs_model_followup,
            context_update=context_update,
            diagnostics={
                "context_owner": "RuntimeContextManager",
                "tool_result_pairing_checked": False,
                "next_turn_required": observation.needs_model_followup,
            },
        )

    def check_invariants(self, snapshot: RuntimeContextSnapshot) -> RuntimeContextInvariantReport:
        pairing_ok = _tool_result_pairing_ok(snapshot.model_messages)
        pressure_level = str(snapshot.token_pressure.get("pressure_level") or "normal")
        needs_compaction = pressure_level in {"high", "critical"}
        return RuntimeContextInvariantReport(
            report_id=f"ctxinv:{snapshot.snapshot_id}",
            snapshot_ref=snapshot.snapshot_id,
            tool_result_pairing_ok=pairing_ok,
            needs_compaction=needs_compaction,
            compaction_reason="token_pressure" if needs_compaction else "",
            token_pressure=dict(snapshot.token_pressure),
            diagnostics={
                "context_owner": "RuntimeContextManager",
                "model_message_count": len(snapshot.model_messages),
                "pressure_level": pressure_level,
                "compaction_executed": False,
                "tool_result_pairing_checked": True,
            },
        )


def _normalize_history(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for item in list(history or []):
        role = str(item.get("role") or "user")
        content = str(item.get("content") or "")
        if not content.strip():
            continue
        messages.append({"role": role, "content": content})
    return messages


def _tool_result_pairing_ok(messages: tuple[dict[str, str], ...]) -> bool:
    # Current model messages do not carry structured tool_use/tool_result
    # ids. The first invariant is therefore conservative: if a future adapter
    # marks a message as tool_result without a paired id, fail the report.
    for item in messages:
        role = str(item.get("role") or "")
        if role == "tool" and not str(item.get("tool_call_id") or ""):
            return False
    return True


def _context_policy_ref(context_policy_result: dict[str, Any] | None) -> str:
    payload = dict(context_policy_result or {})
    package = dict(payload.get("package") or {})
    return str(
        payload.get("result_id")
        or package.get("package_id")
        or package.get("id")
        or package.get("rebuild_reason")
        or ""
    )


def _token_pressure(context_policy_result: dict[str, Any] | None) -> dict[str, Any]:
    package = dict((context_policy_result or {}).get("package") or {})
    return {
        "pressure_level": str(package.get("pressure_level") or "normal"),
        "token_accounting": dict(package.get("token_accounting") or {}),
        "compaction_strategy": str(package.get("compaction_strategy") or "none"),
    }


def _prompt_source_report(
    *,
    stage_projection_snapshot: Any | None,
    context_policy_result: dict[str, Any] | None,
    legacy_system_prompt_chars: int,
    runtime_system_prompt_chars: int,
) -> dict[str, Any]:
    prompt_manifest = dict(getattr(stage_projection_snapshot, "prompt_manifest", {}) or {})
    soul_runtime_view = dict(getattr(stage_projection_snapshot, "soul_runtime_view", {}) or {})
    task_body_orchestration_ref = str(getattr(stage_projection_snapshot, "task_body_orchestration_ref", "") or "")
    runtime_spec_ref = str(getattr(stage_projection_snapshot, "runtime_spec_ref", "") or "")
    context_package = dict((context_policy_result or {}).get("package") or {})
    manifest_sections = []
    for index, section in enumerate(list(prompt_manifest.get("sections") or ())):
        item = dict(section or {})
        manifest_sections.append(
            {
                "order": index,
                "section_id": str(item.get("section_id") or ""),
                "source_type": str(item.get("source_type") or ""),
                "source_id": str(item.get("source_id") or ""),
                "owner_layer": str(item.get("owner_layer") or ""),
                "cache_scope": str(item.get("cache_scope") or ""),
                "visible_to_model": bool(item.get("visible_to_model", True)),
                "chars": int(item.get("chars") or 0),
            }
        )
    model_visible_runtime_sections = _model_visible_projection_sections(stage_projection_snapshot)
    model_visible_ids = {
        str(dict(section or {}).get("section_id") or "")
        for section in model_visible_runtime_sections
    }
    runtime_sections = []
    for index, section in enumerate(list(soul_runtime_view.get("sections") or ())):
        item = dict(section or {})
        runtime_sections.append(
            {
                "order": index,
                "section_id": str(item.get("section_id") or ""),
                "title": str(item.get("title") or ""),
                "owner_layer": str(item.get("owner_layer") or ""),
                "cache_scope": str(item.get("cache_scope") or ""),
                "visible_to_model": str(item.get("section_id") or "") in model_visible_ids,
                "chars": int(item.get("chars") or len(str(item.get("content") or ""))),
            }
        )
    return {
        "assembly_mode": "runtime_prompt_assembly",
        "legacy_system_prompt_chars": legacy_system_prompt_chars,
        "runtime_system_prompt_chars": runtime_system_prompt_chars,
        "projection_ref": str(getattr(stage_projection_snapshot, "projection_ref", "") or ""),
        "prompt_manifest_ref": str(getattr(stage_projection_snapshot, "prompt_manifest_ref", "") or ""),
        "task_body_orchestration_ref": task_body_orchestration_ref,
        "runtime_spec_ref": runtime_spec_ref,
        "manifest_section_count": len(manifest_sections),
        "runtime_section_count": len(model_visible_runtime_sections),
        "context_selected_sections": list(context_package.get("selected_sections") or ()),
        "context_pressure_level": str(context_package.get("pressure_level") or "normal"),
        "manifest_sections": manifest_sections,
        "runtime_sections": runtime_sections,
    }


def _build_runtime_system_prompt(
    *,
    legacy_system_prompt: str,
    stage_projection_snapshot: Any | None,
    context_policy_result: dict[str, Any] | None,
    runtime_execution_facts: dict[str, Any] | None = None,
) -> str:
    parts = [str(legacy_system_prompt or "").strip()]
    projection_block = _render_projection_block(stage_projection_snapshot)
    if projection_block:
        parts.append(projection_block)
    context_block = _render_context_policy_block(context_policy_result)
    if context_block:
        parts.append(context_block)
    runtime_execution_block = _render_runtime_execution_block(runtime_execution_facts)
    if runtime_execution_block:
        parts.append(runtime_execution_block)
    return "\n\n".join(part for part in parts if part)


def _render_projection_block(stage_projection_snapshot: Any | None) -> str:
    if stage_projection_snapshot is None:
        return ""
    sections = []
    for section in _model_visible_projection_sections(stage_projection_snapshot):
        item = dict(section or {})
        title = str(item.get("title") or item.get("section_id") or "Runtime Projection").strip()
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        sections.append(f"### {title}\n{content}")
    if not sections:
        return ""
    header = (
        "## Runtime Stage Projection\n"
        "当前投影只约束本次任务的关注点、角色姿态和输出形态；"
        "它来自正式编排层，不替代身份锚点和共同契约。"
    )
    return "\n\n".join([header, *sections])


def _model_visible_projection_sections(stage_projection_snapshot: Any | None) -> list[dict[str, Any]]:
    if stage_projection_snapshot is None:
        return []
    soul_runtime_view = dict(getattr(stage_projection_snapshot, "soul_runtime_view", {}) or {})
    sections: list[dict[str, Any]] = []
    for section in list(soul_runtime_view.get("sections") or ()):
        item = dict(section or {})
        if item.get("visible_to_model") is False:
            continue
        if _is_control_plane_projection_section(item):
            continue
        if not str(item.get("content") or "").strip():
            continue
        sections.append(item)
    return sections


def _is_control_plane_projection_section(section: dict[str, Any]) -> bool:
    section_id = str(section.get("section_id") or "").strip()
    owner_layer = str(section.get("owner_layer") or "").strip()
    source_type = str(section.get("source_type") or "").strip()
    source_id = str(section.get("source_id") or "").strip()
    source_refs = [str(item or "").strip() for item in list(section.get("source_refs") or ())]
    metadata = dict(section.get("metadata") or {}) if isinstance(section.get("metadata"), dict) else {}
    content = str(section.get("content") or "")
    if section_id in {"resource_section", "guardrail_section"}:
        return True
    if owner_layer in {"resource_policy", "control_kernel", "operation_gate", "commit_gate"}:
        return True
    if source_type in {"resource_policy", "operation_gate", "control_kernel", "commit_gate"}:
        return True
    probe = "\n".join([source_id, *source_refs, content, repr(metadata)]).lower()
    blocked_markers = (
        ":preview",
        "denied:",
        "do not execute tools",
        "runtime_executable=false",
        "runtime_executable: false",
    )
    return any(marker in probe for marker in blocked_markers)


def _render_context_policy_block(context_policy_result: dict[str, Any] | None) -> str:
    package = dict((context_policy_result or {}).get("package") or {})
    model_sections = dict(package.get("model_visible_sections") or package.get("sections") or {})
    section_order = [
        "active_process_context",
        "hot_truth_window",
        "retrieval_evidence",
        "warm_snapshots",
        "exact_durable_context",
        "relevant_durable_context",
    ]
    lines = []
    section_notes = {
        "active_process_context": "当前进行中的任务状态；用于保持推进方向。",
        "hot_truth_window": "近期上下文摘要，用于保持连续性；它不是完整事实源，和当前用户消息或可验证资料冲突时应让位。",
        "retrieval_evidence": "当前检索证据；可用时优先作为回答依据。",
        "warm_snapshots": "较弱的历史线索；仅在和当前任务相关时使用。",
        "exact_durable_context": "精确长期记忆；使用前仍要确认适用范围。",
        "relevant_durable_context": "相关长期记忆；只作为当前判断的辅助依据。",
    }
    for section_name in section_order:
        items = [str(item).strip() for item in list(model_sections.get(section_name) or ()) if str(item).strip()]
        if not items:
            continue
        title = section_name.replace("_", " ").title()
        lines.append(f"### {title}")
        note = section_notes.get(section_name)
        if note:
            lines.append(note)
        lines.extend(f"- {item}" for item in items)
    if not lines:
        return ""
    return "\n".join(
        [
            "## Runtime Context Package",
            "以下内容是本轮运行时上下文，用于辅助当前任务，不覆盖共同契约、当前灵魂、当前用户消息或可验证资料。",
            *lines,
        ]
    )


def _render_runtime_execution_block(runtime_execution_facts: dict[str, Any] | None) -> str:
    facts = dict(runtime_execution_facts or {})
    worker_spawn = dict(facts.get("worker_spawn_summary") or {})
    lines: list[str] = []
    if worker_spawn:
        spawned_agent_ids = [
            str(item).strip()
            for item in list(worker_spawn.get("spawned_agent_ids") or [])
            if str(item).strip()
        ]
        worker_agent_run_ids = [
            str(item).strip()
            for item in list(worker_spawn.get("worker_agent_run_ids") or [])
            if str(item).strip()
        ]
        lines.extend(
            [
                "### Worker Spawn Summary",
                f"- spawn_request_count: {int(worker_spawn.get('spawn_request_count') or 0)}",
                f"- spawn_result_count: {int(worker_spawn.get('spawn_result_count') or 0)}",
                f"- blocked_spawn_count: {int(worker_spawn.get('blocked_spawn_count') or 0)}",
                (
                    f"- spawned_agent_ids: {', '.join(spawned_agent_ids)}"
                    if spawned_agent_ids
                    else "- spawned_agent_ids: none"
                ),
                (
                    f"- worker_agent_run_ids: {', '.join(worker_agent_run_ids)}"
                    if worker_agent_run_ids
                    else "- worker_agent_run_ids: none"
                ),
                "- `worker_sub_agent` 指系统编排层的工作子 Agent，不是浏览器 Web Worker。",
            ]
        )
    if not lines:
        return ""
    return "\n".join(["## Runtime Execution Facts", *lines])


def _snapshot_id(
    *,
    session_id: str,
    task_id: str,
    system_prompt: str,
    history: tuple[dict[str, str], ...],
    pending: str,
    context_policy_ref: str,
    memory_view_ref: str,
    projection_ref: str,
    prompt_manifest_ref: str,
) -> str:
    raw = repr(
        (
            session_id,
            task_id,
            len(system_prompt),
            len(history),
            pending,
            context_policy_ref,
            memory_view_ref,
            projection_ref,
            prompt_manifest_ref,
        )
    )
    return f"ctxsnap:{task_id}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}"
