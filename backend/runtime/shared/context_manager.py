from __future__ import annotations

import hashlib
from pathlib import Path
from datetime import datetime
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .action_request import RuntimeObservation
from runtime.context_management import build_tool_use_summary, estimate_json_bytes, microcompact_history


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
        runtime_assembly: dict[str, Any] | None = None,
        agent_assembly_contract: dict[str, Any] | None = None,
    ) -> RuntimeContextSnapshot:
        system_prompt = self.system_prompt_builder(
            session_id=session_id,
            pending_user_message=user_message,
            memory_intent=memory_intent,
        )
        assembly_policy = _runtime_assembly_context_policy(runtime_assembly)
        history_compaction = {
            "applied": False,
            "mode": "history_microcompact",
            "compacted_message_count": 0,
            "content_replacements": [],
        }
        normalized_history_list = _normalize_history(history)
        token_pressure = _token_pressure(context_policy_result)
        token_pressure = _merge_actual_history_pressure(
            token_pressure,
            history=normalized_history_list,
            pending_user_message=user_message,
        )
        if assembly_policy.get("main_session_history") != "full":
            normalized_history_list = []
        else:
            normalized_history_list, history_compaction = microcompact_history(
                normalized_history_list,
                root_dir=_runtime_context_root(runtime_assembly=runtime_assembly, agent_assembly_contract=agent_assembly_contract),
                session_id=session_id,
                task_id=task_id,
            )
        normalized_history = tuple(normalized_history_list)
        pending = str(user_message or "")
        context_policy_ref = _context_policy_ref(context_policy_result)
        memory_view_ref = str((memory_runtime_view or {}).get("view_id") or "")
        projection_ref = str(getattr(stage_projection_snapshot, "projection_ref", "") or "")
        prompt_manifest_ref = str(getattr(stage_projection_snapshot, "prompt_manifest_ref", "") or "")
        runtime_prompt = _build_runtime_system_prompt(
            base_system_prompt=system_prompt,
            stage_projection_snapshot=stage_projection_snapshot,
            context_policy_result=context_policy_result,
            runtime_execution_facts=runtime_execution_facts,
            runtime_assembly=runtime_assembly,
            agent_assembly_contract=agent_assembly_contract,
        )
        model_messages = (
            {"role": "system", "content": runtime_prompt},
            *normalized_history,
            {"role": "user", "content": pending},
        )
        history_message_count = len(normalized_history)
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
            history_message_count=history_message_count,
            pending_user_message_chars=len(pending),
            system_prompt_chars=len(runtime_prompt),
            token_pressure=token_pressure,
            prompt_source_report=_prompt_source_report(
                stage_projection_snapshot=stage_projection_snapshot,
                context_policy_result=context_policy_result,
                base_system_prompt_chars=len(system_prompt),
                runtime_system_prompt_chars=len(runtime_prompt),
            ),
            context_policy_ref=context_policy_ref,
            memory_runtime_view_ref=memory_view_ref,
            projection_ref=projection_ref,
            prompt_manifest_ref=prompt_manifest_ref,
            diagnostics={
                "context_owner": "RuntimeContextManager",
                "model_message_count": len(model_messages),
                "compression_applied": bool(history_compaction.get("applied") is True),
                "history_compaction": history_compaction,
                "context_compactor_agent_required": str(token_pressure.get("pressure_level") or "normal") in {"high", "critical"},
                "tool_result_pairing_checked": False,
                "stage_projection_consumed": bool(stage_projection_snapshot is not None),
                "prompt_manifest_bound": bool(prompt_manifest_ref),
                "prompt_source_report_built": True,
                "runtime_prompt_assembly_applied": True,
                "runtime_assembly_ref": str((runtime_assembly or {}).get("assembly_id") or ""),
                "runtime_assembly_context_applied": bool(runtime_assembly),
                "agent_assembly_contract_ref": str((agent_assembly_contract or {}).get("assembly_id") or ""),
                "agent_assembly_contract_applied": bool(agent_assembly_contract),
                "assembly_main_session_history": str(assembly_policy.get("main_session_history") or ""),
            },
        )

    def record_observation(self, observation: RuntimeObservation) -> RuntimeContextObservationRecord:
        """Normalize an observation into a future context update.

        The current single-agent lane does not mutate model_messages after the
        final answer. This record is the durable slot that tool_result and
        worker_result observations will use before a next_turn model call.
        """

        tool_summary = build_tool_use_summary(observation)
        context_update = {
            "mode": "no_followup_required" if not observation.needs_model_followup else "append_for_next_turn",
            "content_chars": observation.content_chars,
            "observation_type": observation.observation_type,
        }
        if tool_summary is not None:
            context_update["tool_use_summary"] = tool_summary.to_dict()
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
                "tool_use_summary_built": tool_summary is not None,
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
    base_system_prompt_chars: int,
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
        "base_system_prompt_chars": base_system_prompt_chars,
        "runtime_system_prompt_chars": runtime_system_prompt_chars,
        "projection_ref": str(getattr(stage_projection_snapshot, "projection_ref", "") or ""),
        "prompt_manifest_ref": str(getattr(stage_projection_snapshot, "prompt_manifest_ref", "") or ""),
        "prompt_manifest_validation": dict(prompt_manifest.get("validation") or {}),
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
    base_system_prompt: str,
    stage_projection_snapshot: Any | None,
    context_policy_result: dict[str, Any] | None,
    runtime_execution_facts: dict[str, Any] | None = None,
    runtime_assembly: dict[str, Any] | None = None,
    agent_assembly_contract: dict[str, Any] | None = None,
) -> str:
    parts = [str(base_system_prompt or "").strip()]
    agent_assembly_block = _render_agent_assembly_contract_block(agent_assembly_contract)
    if agent_assembly_block:
        parts.append(agent_assembly_block)
    projection_block = _render_projection_block(stage_projection_snapshot)
    if projection_block:
        parts.append(projection_block)
    context_block = _render_context_policy_block(context_policy_result)
    if context_block:
        parts.append(context_block)
    runtime_execution_block = _render_runtime_execution_block(runtime_execution_facts)
    if runtime_execution_block:
        parts.append(runtime_execution_block)
    runtime_assembly_block = _render_runtime_assembly_block(runtime_assembly)
    if runtime_assembly_block:
        parts.append(runtime_assembly_block)
    delegation_guidance_block = _render_agent_delegation_guidance_block(runtime_assembly)
    if delegation_guidance_block:
        parts.append(delegation_guidance_block)
    return "\n\n".join(part for part in parts if part)


def _render_agent_assembly_contract_block(agent_assembly_contract: dict[str, Any] | None) -> str:
    assembly = dict(agent_assembly_contract or {})
    if not assembly:
        return ""
    prompt = dict(assembly.get("prompt_assembly") or {})
    role_name = str(prompt.get("role_name") or "执行代理").strip() or "执行代理"
    role_summary = str(prompt.get("role_summary") or "").strip()
    instruction_text = str(prompt.get("instruction_text") or "").strip()
    required_outputs = [
        str(item).strip()
        for item in list(prompt.get("required_outputs") or [])
        if str(item).strip()
    ]
    forbidden_actions = [
        str(item).strip()
        for item in list(prompt.get("forbidden_actions") or [])
        if str(item).strip()
    ]
    output_boundary = dict(assembly.get("output_boundary") or {})
    delivery = _delivery_label(str(output_boundary.get("selected_channel") or ""))
    lines = [
        "## 当前 Agent 工作契约",
        f"你是一名{role_name}。",
    ]
    if role_summary:
        lines.append(role_summary)
    if instruction_text:
        lines.append(instruction_text)
    if delivery:
        lines.append(f"你的最终交付应是：{delivery}。")
    if required_outputs:
        lines.append("必须交付：" + "，".join(required_outputs))
    if forbidden_actions:
        lines.append("禁止事项：" + "，".join(forbidden_actions))
    lines.append("不要把装配字段、节点编号、权限记录或运行状态当作用户可见内容输出。")
    return "\n".join(line for line in lines if line)


def _delivery_label(channel: str) -> str:
    return {
        "assistant_message": "面向用户的最终回答",
        "graph_node_result": "当前阶段任务结果",
        "human_review": "人工审核反馈",
        "subruntime_result": "子任务结果",
    }.get(str(channel or "").strip(), "当前任务结果")


def _runtime_assembly_context_policy(runtime_assembly: dict[str, Any] | None) -> dict[str, str]:
    assembly = dict(runtime_assembly or {})
    if not assembly:
        return {"main_session_history": "full"}
    sections = [dict(item or {}) for item in list(assembly.get("context_sections") or []) if isinstance(item, dict)]
    main_history = next((item for item in sections if str(item.get("section_id") or "") == "main_session_history"), None)
    if main_history is None:
        return {"main_session_history": "hidden"}
    return {"main_session_history": str(main_history.get("content_mode") or "summary").strip() or "summary"}


def _runtime_context_root(*, runtime_assembly: dict[str, Any] | None, agent_assembly_contract: dict[str, Any] | None) -> Path:
    for payload in (runtime_assembly, agent_assembly_contract):
        data = dict(payload or {})
        for key in ("root_dir", "workspace_root", "backend_root"):
            value = str(data.get(key) or "").strip()
            if value:
                return Path(value)
    return Path(".")


def _render_runtime_assembly_block(runtime_assembly: dict[str, Any] | None) -> str:
    assembly = dict(runtime_assembly or {})
    if not assembly:
        return ""
    sections = [
        dict(item or {})
        for item in list(assembly.get("context_sections") or [])
        if isinstance(item, dict) and dict(item).get("model_visible") is not False
    ]
    if not sections:
        return ""
    lines = ["## 可用参考材料"]
    for section in sections:
        title = str(section.get("title") or section.get("label") or section.get("section_id") or "").strip()
        mode = str(section.get("content_mode") or "").strip()
        if title and mode:
            lines.append(f"- {title}：{mode}")
        elif title:
            lines.append(f"- {title}")
    return "\n".join(lines)


def _render_agent_delegation_guidance_block(runtime_assembly: dict[str, Any] | None) -> str:
    assembly = dict(runtime_assembly or {})
    if str(assembly.get("agent_id") or "") != "agent:0":
        return ""
    return "\n".join(
        [
            "## 专业子 Agent 调度方式",
            "你是主 Agent。遇到需要专业证据、PDF 阅读、表格分析、多源搜索核验或交付复核的问题时，可以把边界清楚的子任务交给内置专业子 Agent，自己负责最终整合和回答。",
            "- `agent:rag_analyst` / `evidence_lookup`：适合从知识库或检索证据中找依据、出处和可引用片段。",
            "- `agent:pdf_reader` / `pdf_reading`：适合读取明确的 PDF、指定页码、章节或全文总览。",
            "- `agent:table_analyst` / `table_analysis`：适合 Excel、CSV、数据表的筛选、排序、分组汇总、缺口计算和口径说明。",
            "- `agent:web_researcher` / `web_research` / `evidence_lookup` / `local_search` / `memory_lookup`：适合按配置检索公开网页、本地文件、知识库和正式记忆，并整理可追溯证据。",
            "- `agent:verifier` / `completion_verification`：适合在已有候选回答、产物或证据后，独立检查是否覆盖用户目标、是否有无证据声明、是否需要返工。",
            "委派时请像给专业同事派任务一样，把目标对象、文件路径、页码、数据口径、查询主题、时效要求、来源范围和用户真正要的输出一次说明清楚。",
            "子 Agent 的结果是专业证据包或复核意见，不是最终回复。你需要根据它的摘要、证据引用、产物引用、裁决和限制说明，给用户一个清楚、诚实、可继续推进的答案。",
            "如果子 Agent 明确说明信息不足，请解释缺什么和为什么影响结论；如果已经有足够结果，请直接收口，不要把内部执行步骤暴露给用户。",
        ]
    )


def _render_projection_block(stage_projection_snapshot: Any | None) -> str:
    if stage_projection_snapshot is None:
        return ""
    sections = []
    for section in _model_visible_projection_sections(stage_projection_snapshot):
        item = dict(section or {})
        title = str(item.get("title") or item.get("section_id") or "本轮任务要求").strip()
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        sections.append(f"### {title}\n{content}")
    if not sections:
        return ""
    header = (
        "## 本轮执行角色\n"
        "以下内容用于确定本轮任务职责、语气和交付形态。"
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
    allow_hot_truth = _context_package_allows_hot_truth_prompt(package)
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
        if section_name == "hot_truth_window" and not allow_hot_truth:
            continue
        items = [
            str(item).strip()
            for item in list(model_sections.get(section_name) or ())
            if str(item).strip()
        ]
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


def _merge_actual_history_pressure(
    token_pressure: dict[str, Any],
    *,
    history: list[dict[str, str]],
    pending_user_message: str,
    high_bytes: int = 120_000,
    critical_bytes: int = 220_000,
) -> dict[str, Any]:
    actual_bytes = estimate_json_bytes({"history": history, "pending_user_message": pending_user_message})
    upstream = str(token_pressure.get("pressure_level") or "normal")
    actual = "normal"
    if actual_bytes >= critical_bytes:
        actual = "critical"
    elif actual_bytes >= high_bytes:
        actual = "high"
    merged = _max_pressure(upstream, actual)
    return {
        **dict(token_pressure),
        "pressure_level": merged,
        "actual_context_bytes": actual_bytes,
        "actual_pressure_level": actual,
        "pressure_source": "actual_history" if merged != upstream else "context_policy",
    }


def _max_pressure(first: str, second: str) -> str:
    order = {"normal": 0, "medium": 1, "high": 2, "critical": 3}
    return first if order.get(str(first or "normal"), 0) >= order.get(str(second or "normal"), 0) else second


def _context_package_allows_hot_truth_prompt(package: dict[str, Any]) -> bool:
    rebuild_reason = str(package.get("rebuild_reason") or "").lower()
    compaction_strategy = str(package.get("compaction_strategy") or "").lower()
    if compaction_strategy and compaction_strategy != "none":
        return True
    return any(marker in rebuild_reason for marker in ("compact", "compaction", "recovery", "restore"))


def _render_runtime_execution_block(runtime_execution_facts: dict[str, Any] | None) -> str:
    facts = dict(runtime_execution_facts or {})
    worker_spawn = dict(facts.get("worker_spawn_summary") or {})
    capability_state = dict(facts.get("runtime_capability_state") or {})
    current_time_fact = _resolve_runtime_current_time_fact(facts, capability_state)
    lines: list[str] = []
    if current_time_fact:
        timezone_label = str(current_time_fact.get("timezone") or "").strip()
        local_date = str(current_time_fact.get("local_date") or "").strip()
        local_time = str(current_time_fact.get("local_time") or "").strip()
        lines.extend(
            [
                "### Current Time Facts",
                "以下时间由系统在本轮运行时生成，用于解释今天、当前、现在、latest 这类时间词。",
            ]
        )
        if timezone_label:
            lines.append(f"- 当前时区：{timezone_label}。")
        if local_date:
            lines.append(f"- 当前本地日期：{local_date}。")
        if local_time:
            lines.append(f"- 当前本地时间：{local_time}。")
        lines.extend(
            [
                "- 对“今天”“当前”“现在”“latest”这类时间词，默认按上述本地时间理解。",
                "- 历史回答中的时间戳只表示当时证据时间，不能直接当作本轮实时查询的当前日期。",
            ]
        )
    if capability_state:
        profile_write_capable = bool(capability_state.get("profile_write_capable"))
        turn_write_adopted = bool(capability_state.get("turn_write_operation_adopted"))
        turn_write_visible = bool(capability_state.get("turn_write_tool_visible"))
        visible_tools = [
            str(item).strip()
            for item in list(capability_state.get("turn_visible_tools") or [])
            if str(item).strip()
        ]
        adopted_operations = [
            str(item).strip()
            for item in list(capability_state.get("turn_adopted_operations") or [])
            if str(item).strip()
        ]
        lines.extend(
            [
                "### Agent Capability Boundary",
                "这一层说明能力边界，不会给本轮额外授权，也不要求你执行未被当前任务采用的工具。",
                f"- Agent 配置上限允许文件写入/编辑：{'是' if profile_write_capable else '否'}。",
                f"- 本轮任务已采用写入/编辑 operation：{'是' if turn_write_adopted else '否'}。",
                f"- 本轮模型可见写入/编辑工具：{'是' if turn_write_visible else '否'}。",
                "- 当前可见工具只代表本轮执行面，不能反推出 Agent 的总能力。",
                "- 历史对话或记忆中的 Assistant 自我能力判断不能覆盖这一运行时能力状态。",
            ]
        )
        if visible_tools:
            lines.append(f"- 本轮可见工具：{', '.join(visible_tools)}。")
        else:
            lines.append("- 本轮没有额外模型可见工具；这只表示当前任务没有采用这些工具。")
        if adopted_operations:
            lines.append(f"- 本轮采用 operation：{', '.join(adopted_operations)}。")
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
                "- 这里的 worker agent 指系统编排层生成或调用的执行 Agent，不是浏览器 Web Worker。",
            ]
        )
    if not lines:
        return ""
    return "\n".join(["## Runtime Execution Facts", *lines])


def _resolve_runtime_current_time_fact(
    facts: dict[str, Any],
    capability_state: dict[str, Any],
) -> dict[str, str]:
    explicit_fact = dict(facts.get("current_time_fact") or {})
    if explicit_fact:
        return {
            "timezone": str(explicit_fact.get("timezone") or "").strip(),
            "local_date": str(explicit_fact.get("local_date") or "").strip(),
            "local_time": str(explicit_fact.get("local_time") or "").strip(),
        }
    if not _should_expose_current_time_fact(capability_state):
        return {}
    now = datetime.now().astimezone()
    timezone_label = str(now.tzinfo or "").strip() or "local"
    return {
        "timezone": timezone_label,
        "local_date": now.date().isoformat(),
        "local_time": now.isoformat(timespec="minutes"),
    }


def _should_expose_current_time_fact(capability_state: dict[str, Any]) -> bool:
    operations = {
        str(item).strip()
        for item in [
            *list(capability_state.get("turn_requested_operations") or []),
            *list(capability_state.get("turn_adopted_operations") or []),
        ]
        if str(item).strip()
    }
    return "op.web_search" in operations


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
