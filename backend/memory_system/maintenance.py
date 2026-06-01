from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, Field, field_validator

from project_layout import ProjectLayout
from memory_system.storage.models import MemoryNote
from memory_system.storage.text_utils import normalize_storage_text

from .manifest_scan import scan_memory_headers
from .paths import normalize_session_id, safe_runtime_session_key


MEMORY_MANAGER_AGENT_ID = "agent:1"
MEMORY_MANAGER_PROFILE_ID = "memory_system_agent"
ALLOWED_DURABLE_MEMORY_TYPES = {"user", "feedback", "project", "reference"}
ALLOWED_DURABLE_MEMORY_CLASSES = {"work", "preference"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def normalize_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.splitlines() if item.strip()]
    if isinstance(value, (list, tuple)):
        return [normalize_text(item) for item in value if normalize_text(item)]
    return [normalize_text(value)] if normalize_text(value) else []


class SessionMemoryMaintenanceDraft(BaseModel):
    session_title: str = ""
    active_goal: str = ""
    flow_state: list[str] = Field(default_factory=list)
    context_slots: list[str] = Field(default_factory=list)
    current_task_state: list[str] = Field(default_factory=list)
    warm_context: list[str] = Field(default_factory=list)
    key_user_requests: list[str] = Field(default_factory=list)
    files_and_functions: list[str] = Field(default_factory=list)
    conventions_and_constraints: list[str] = Field(default_factory=list)
    errors_and_corrections: list[str] = Field(default_factory=list)
    decisions_and_learnings: list[str] = Field(default_factory=list)
    key_results: list[str] = Field(default_factory=list)
    historical_results: list[str] = Field(default_factory=list)
    risk_watch: list[str] = Field(default_factory=list)
    next_step: list[str] = Field(default_factory=list)
    worklog: list[str] = Field(default_factory=list)

    @field_validator(
        "flow_state",
        "context_slots",
        "current_task_state",
        "warm_context",
        "key_user_requests",
        "files_and_functions",
        "conventions_and_constraints",
        "errors_and_corrections",
        "decisions_and_learnings",
        "key_results",
        "historical_results",
        "risk_watch",
        "next_step",
        "worklog",
        mode="before",
    )
    @classmethod
    def _coerce_list(cls, value: Any) -> list[str]:
        return normalize_text_list(value)

    @field_validator("session_title", "active_goal", mode="before")
    @classmethod
    def _coerce_text(cls, value: Any) -> str:
        return normalize_text(value)

    def is_empty(self) -> bool:
        if self.session_title or self.active_goal:
            return False
        return not any(
            (
                self.flow_state,
                self.context_slots,
                self.current_task_state,
                self.warm_context,
                self.key_user_requests,
                self.files_and_functions,
                self.conventions_and_constraints,
                self.errors_and_corrections,
                self.decisions_and_learnings,
                self.key_results,
                self.historical_results,
                self.risk_watch,
                self.next_step,
                self.worklog,
            )
        )

    def render_markdown(self) -> str:
        sections: list[tuple[str, list[str]]] = [
            ("# Session Title", [self.session_title] if self.session_title else []),
            ("# Active Goal", [self.active_goal] if self.active_goal else []),
            ("# Flow State", self.flow_state),
            ("# Context Slots", self.context_slots),
            ("# Current Task State", self.current_task_state),
            ("# Warm Context", self.warm_context),
            ("# Key User Requests", self.key_user_requests),
            ("# Files and Functions", self.files_and_functions),
            ("# Conventions and Constraints", self.conventions_and_constraints),
            ("# Errors and Corrections", self.errors_and_corrections),
            ("# Decisions and Learnings", self.decisions_and_learnings),
            ("# Key Results", self.key_results),
            ("# Historical Results", self.historical_results),
            ("# Risk Watch", self.risk_watch),
            ("# Next Step", self.next_step),
            ("# Worklog", self.worklog),
        ]
        chunks: list[str] = []
        for header, items in sections:
            chunks.append(header)
            for item in items:
                text = normalize_text(item)
                if not text:
                    continue
                if header == "# Session Title":
                    chunks.append(text)
                elif text.startswith("- "):
                    chunks.append(text)
                else:
                    chunks.append(f"- {text}")
            chunks.append("")
        return "\n".join(chunks).strip() + "\n"


class DurableMemoryWriteAction(BaseModel):
    action: Literal["none", "create", "update", "merge"] = "none"
    note_id: str = ""
    target_note_id: str = ""
    merge_note_ids: list[str] = Field(default_factory=list)
    memory_type: Literal["user", "feedback", "project", "reference"] = "project"
    memory_class: Literal["work", "preference"] = "work"
    title: str = ""
    canonical_statement: str = ""
    summary: str = ""
    retrieval_hints: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    reason: str = ""
    how_to_apply: str = ""
    evidence_excerpt: str = ""
    source_message_refs: list[str] = Field(default_factory=list)

    @field_validator(
        "note_id",
        "target_note_id",
        "title",
        "canonical_statement",
        "summary",
        "reason",
        "how_to_apply",
        "evidence_excerpt",
        mode="before",
    )
    @classmethod
    def _coerce_text(cls, value: Any) -> str:
        return normalize_text(value)

    @field_validator("retrieval_hints", "source_message_refs", "merge_note_ids", mode="before")
    @classmethod
    def _coerce_list(cls, value: Any) -> list[str]:
        return normalize_text_list(value)


class DurableMemoryWritePlan(BaseModel):
    actions: list[DurableMemoryWriteAction] = Field(default_factory=list)
    skipped_reason: str = ""
    reasoning_summary: str = ""

    @field_validator("skipped_reason", "reasoning_summary", mode="before")
    @classmethod
    def _coerce_text(cls, value: Any) -> str:
        return normalize_text(value)

    def normalized_actions(self) -> list[DurableMemoryWriteAction]:
        return [item for item in self.actions if item.action != "none"]


class MemoryMaintenanceProposal(BaseModel):
    session_memory: SessionMemoryMaintenanceDraft
    durable_memory: DurableMemoryWritePlan = Field(default_factory=DurableMemoryWritePlan)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    authority: Literal["memory_maintenance_agent.proposal"] = "memory_maintenance_agent.proposal"


class MemoryMaintenanceRequest(BaseModel):
    run_id: str
    session_id: str
    turn_id: str = ""
    agent_id: str = MEMORY_MANAGER_AGENT_ID
    message_count: int = 0
    last_memory_message_index: int = 0
    message_slice: list[dict[str, Any]] = Field(default_factory=list)
    previous_session_memory: str = ""
    main_context: dict[str, Any] = Field(default_factory=dict)
    task_summary_refs: list[dict[str, Any]] = Field(default_factory=list)
    bundle_summary_refs: list[dict[str, Any]] = Field(default_factory=list)
    manifest_headers: list[dict[str, Any]] = Field(default_factory=list)
    source_message_refs: list[str] = Field(default_factory=list)
    durable_lane_enabled: bool = True


class MemoryMaintenanceReceipt(BaseModel):
    run_id: str
    session_id: str
    turn_id: str = ""
    agent_id: str = MEMORY_MANAGER_AGENT_ID
    status: Literal["succeeded", "failed", "skipped", "queued"] = "skipped"
    attempted: bool = False
    queued: bool = False
    session_memory_succeeded: bool = False
    durable_memory_succeeded: bool = False
    durable_write_count: int = 0
    durable_skipped: bool = False
    durable_skip_reason: str = ""
    last_memory_message_index: int = 0
    processed_message_count: int = 0
    error: str = ""
    receipt_path: str = ""
    created_at: str = Field(default_factory=utc_now_iso)
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


MessageInvoker = Callable[[list[dict[str, str]]], Awaitable[object]]


class MemoryMaintenanceAgent:
    """Model-backed agent:1 implementation that returns proposals only."""

    def __init__(self, *, message_invoker: MessageInvoker | None = None) -> None:
        self._message_invoker = message_invoker

    def set_message_invoker(self, message_invoker: MessageInvoker | None) -> None:
        self._message_invoker = message_invoker

    async def maintain(self, request: MemoryMaintenanceRequest) -> MemoryMaintenanceProposal:
        if self._message_invoker is None:
            raise RuntimeError("memory maintenance model invoker is not configured")
        response = await self._message_invoker(
            [
                {"role": "system", "content": self.system_prompt()},
                {"role": "user", "content": self._user_payload(request)},
            ]
        )
        payload = self._extract_json(self._response_text(response))
        return self._proposal_from_payload(payload)

    def system_prompt(self) -> str:
        return (
            "你是一名记忆管理员。\n"
            "你只负责整理当前会话中对后续继续工作有帮助的信息，并判断是否存在值得跨会话保存的稳定记忆。\n"
            "你不回答用户，不推进任务，不修复问题，也不替主 Agent 做任务决策。\n"
            "你需要区分会话恢复信息和跨会话长期记忆。\n"
            "Session Memory 只服务当前会话的 compact/recovery，要记录当前目标、工作状态、关键文件、结果、纠错和下一步。\n"
            "Durable Memory 只保存跨会话仍然有价值、稳定、非显而易见的信息，分类只能是 user、feedback、project、reference。\n"
            "不要把临时运行状态、工具失败、调度限制、runtime 诊断、可从当前文件或索引重新推导的信息写入长期记忆。\n"
            "不要保存代码模式、Git 历史、调试方案、已存在于项目指令中的规则，或只对本轮任务有用的过程记录。\n"
            "如果没有可靠的长期记忆，durable_memory.actions 返回空数组，并说明 skipped_reason。\n"
            "每条长期记忆写入都必须包含 evidence_excerpt 和 source_message_refs。\n"
            "你只能输出 JSON，不要输出 Markdown、解释或给用户看的回答。"
        )

    def _user_payload(self, request: MemoryMaintenanceRequest) -> str:
        schema_hint = {
            "session_memory": {
                "session_title": "短标题",
                "active_goal": "当前用户目标",
                "flow_state": ["当前流程状态"],
                "context_slots": ["当前有效上下文绑定，只记录当前仍有用的事实"],
                "current_task_state": ["正在处理或刚完成的事项"],
                "warm_context": ["继续工作时仍有帮助的短上下文"],
                "key_user_requests": ["用户明确提出且当前会话仍适用的要求"],
                "files_and_functions": ["相关文件、模块、函数"],
                "conventions_and_constraints": ["当前会话约束"],
                "errors_and_corrections": ["需要避免重复的问题或纠正"],
                "decisions_and_learnings": ["本会话形成的结论"],
                "key_results": ["本轮或当前阶段的关键结果"],
                "historical_results": ["旧结果，仅调试或恢复时参考"],
                "risk_watch": ["仍需注意的风险"],
                "next_step": ["自然继续时的下一步"],
                "worklog": ["简短事件记录"],
            },
            "durable_memory": {
                "actions": [
                    {
                        "action": "create | update | merge",
                        "note_id": "新建时可给稳定短 id",
                        "target_note_id": "更新或合并目标",
                        "merge_note_ids": ["合并来源"],
                        "memory_type": "user | feedback | project | reference",
                        "memory_class": "work | preference",
                        "title": "记忆标题",
                        "canonical_statement": "稳定事实",
                        "summary": "简短摘要",
                        "retrieval_hints": ["召回提示"],
                        "confidence": "low | medium | high",
                        "reason": "为什么值得长期保存",
                        "how_to_apply": "以后如何使用",
                        "evidence_excerpt": "来自本轮消息的证据摘录",
                        "source_message_refs": ["message:最后消息索引等来源引用"],
                    }
                ],
                "skipped_reason": "没有写入时说明原因",
                "reasoning_summary": "极短内部判断摘要",
            },
        }
        return json.dumps({"request": request.model_dump(), "output_schema": schema_hint}, ensure_ascii=False, indent=2)

    def _proposal_from_payload(self, payload: dict[str, Any]) -> MemoryMaintenanceProposal:
        session_payload = payload.get("session_memory")
        if not isinstance(session_payload, dict):
            raise ValueError("memory maintenance response missing session_memory object")
        durable_payload = payload.get("durable_memory")
        if not isinstance(durable_payload, dict):
            durable_payload = {}
        return MemoryMaintenanceProposal(
            session_memory=SessionMemoryMaintenanceDraft.model_validate(session_payload),
            durable_memory=DurableMemoryWritePlan.model_validate(durable_payload),
            diagnostics={
                "response_keys": sorted(str(key) for key in payload.keys()),
                "agent_id": MEMORY_MANAGER_AGENT_ID,
                "agent_profile_id": MEMORY_MANAGER_PROFILE_ID,
                "proposal_only": True,
            },
        )

    def _response_text(self, response: object) -> str:
        content = getattr(response, "content", "")
        if isinstance(content, list):
            return "".join(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        return str(content or "")

    def _extract_json(self, text: str) -> dict[str, Any]:
        stripped = str(text or "").strip()
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError("Memory maintenance response must be a JSON object")
        return payload


class MemoryCommitter:
    """System authority that validates and commits memory proposals."""

    def __init__(
        self,
        *,
        session_memory_layer: Any,
        memory_manager: Any,
        on_durable_saved: Callable[[int], None] | None = None,
    ) -> None:
        self.session_memory_layer = session_memory_layer
        self.memory_manager = memory_manager
        self.on_durable_saved = on_durable_saved

    def set_durable_saved_callback(self, callback: Callable[[int], None] | None) -> None:
        self.on_durable_saved = callback

    def commit(
        self,
        request: MemoryMaintenanceRequest,
        proposal: MemoryMaintenanceProposal,
    ) -> dict[str, Any]:
        if proposal.session_memory.is_empty():
            raise ValueError("memory maintenance agent returned empty session memory")
        manager = self.session_memory_layer.manager(request.session_id)
        rendered_session = proposal.session_memory.render_markdown()
        manager.overwrite(rendered_session, debug_content=rendered_session)

        durable_commit = self.commit_durable_plan(request, proposal.durable_memory)
        return {
            "session_memory_succeeded": True,
            **durable_commit,
        }

    def commit_durable_plan(
        self,
        request: MemoryMaintenanceRequest,
        plan: DurableMemoryWritePlan,
    ) -> dict[str, Any]:
        durable_count = 0
        durable_skipped = True
        durable_skip_reason = ""
        durable_error = ""
        durable_actions = {"created": [], "updated": [], "merged": [], "deprecated": [], "rejected": []}
        if not request.durable_lane_enabled:
            durable_skip_reason = "durable_lane_disabled"
        else:
            try:
                actions = plan.normalized_actions()
                if actions:
                    durable_skipped = False
                    for action in actions:
                        applied = self._apply_durable_action(action, request=request)
                        for key, values in applied.items():
                            durable_actions.setdefault(key, []).extend(values)
                        durable_count += 1
                    if self.on_durable_saved is not None and durable_count > 0:
                        self.on_durable_saved(durable_count)
                else:
                    durable_skip_reason = plan.skipped_reason or "agent_returned_no_durable_actions"
            except Exception as exc:
                durable_skipped = True
                durable_error = str(exc)
                durable_actions["rejected"].append(durable_error)
                durable_skip_reason = "durable_write_rejected_by_committer"
        return {
            "durable_memory_succeeded": bool(request.durable_lane_enabled and not durable_error),
            "durable_write_count": durable_count,
            "durable_skipped": durable_skipped,
            "durable_skip_reason": durable_skip_reason,
            "durable_error": durable_error,
            "durable_actions": durable_actions,
        }

    def _apply_durable_action(self, action: DurableMemoryWriteAction, *, request: MemoryMaintenanceRequest) -> dict[str, list[str]]:
        note = self._note_from_action(action, request=request)
        self._assert_note_path_in_memory_dir(note.slug)
        if action.action == "create":
            if action.target_note_id:
                raise ValueError("durable create action must not include target_note_id")
            self.memory_manager.save_note(note)
            return {"created": [note.slug]}
        if action.action == "update":
            target = str(action.target_note_id or action.note_id or "").strip()
            if not target:
                raise ValueError("durable update action requires target_note_id")
            target_slug = self.memory_manager.slugify(target)
            if not self.memory_manager.note_exists(target_slug):
                raise KeyError(f"Unknown durable memory update target: {target_slug}")
            self.memory_manager.update_note(target_slug, patch=note)
            return {"updated": [target_slug]}
        if action.action == "merge":
            merge_ids = [
                self.memory_manager.slugify(item)
                for item in list(action.merge_note_ids or [])
                if str(item or "").strip()
            ]
            if len(merge_ids) < 2:
                raise ValueError("durable merge action requires at least two merge_note_ids")
            for slug in merge_ids:
                if not self.memory_manager.note_exists(slug):
                    raise KeyError(f"Unknown durable memory merge source: {slug}")
            target = self.memory_manager.slugify(action.target_note_id or action.note_id or note.slug)
            note.slug = target
            self.memory_manager.save_note(note)
            deprecated = self.memory_manager.deprecate_notes(
                [slug for slug in merge_ids if slug != target],
                replacement_slug=target,
                reason=action.reason or "durable_memory_merge",
                actor=MEMORY_MANAGER_AGENT_ID,
                source_evidence_ref=action.evidence_excerpt,
                metadata={
                    "operation": "memory_committer.merge",
                    "run_id": request.run_id,
                    "source_message_refs": list(action.source_message_refs or request.source_message_refs),
                },
            )
            return {"merged": [target], "deprecated": deprecated}
        raise ValueError(f"unsupported durable memory action: {action.action}")

    def _note_from_action(self, action: DurableMemoryWriteAction, *, request: MemoryMaintenanceRequest) -> MemoryNote:
        if action.memory_type not in ALLOWED_DURABLE_MEMORY_TYPES:
            raise ValueError(f"invalid durable memory type: {action.memory_type}")
        if action.memory_class not in ALLOWED_DURABLE_MEMORY_CLASSES:
            raise ValueError(f"invalid durable memory class: {action.memory_class}")
        canonical = normalize_storage_text(action.canonical_statement)
        title = normalize_storage_text(action.title) or canonical[:48]
        evidence = normalize_storage_text(action.evidence_excerpt)
        source_refs = list(action.source_message_refs or request.source_message_refs)
        if not canonical or not title:
            raise ValueError("durable memory action missing title or canonical statement")
        if not evidence or not source_refs:
            raise ValueError("durable memory action missing evidence or source message refs")
        note_id = action.target_note_id or action.note_id or title or canonical
        slug = self.memory_manager.slugify(note_id)
        summary = normalize_storage_text(action.summary) or canonical[:120]
        hints = self._dedupe([canonical, title, summary, *list(action.retrieval_hints or [])])[:8]
        body = self._durable_body(
            canonical=canonical,
            reason=action.reason,
            how_to_apply=action.how_to_apply,
            evidence=evidence,
            source_refs=source_refs,
            run_id=request.run_id,
        )
        return MemoryNote(
            slug=slug,
            title=title,
            summary=summary,
            canonical_statement=canonical,
            body=body,
            memory_type=action.memory_type,
            memory_class=action.memory_class,
            tags=self._dedupe([action.memory_type, action.memory_class, *hints[:4]]),
            retrieval_hints=hints,
            created_by=MEMORY_MANAGER_AGENT_ID,
            source_session_id=request.session_id,
            source_role="conversation",
            source_message_excerpt=evidence[:160],
            confidence=action.confidence,
            source_kind="memory_maintenance_agent",
            eligible_for_injection="true",
        )

    def _durable_body(
        self,
        *,
        canonical: str,
        reason: str,
        how_to_apply: str,
        evidence: str,
        source_refs: list[str],
        run_id: str,
    ) -> str:
        lines = [
            "## Canonical Memory",
            canonical,
            "",
            "## Why Stored",
            normalize_storage_text(reason) or "Agent judged this as stable cross-session memory.",
        ]
        if normalize_storage_text(how_to_apply):
            lines.extend(["", "## How To Apply", normalize_storage_text(how_to_apply)])
        lines.extend(
            [
                "",
                "## Source Evidence",
                evidence,
                "",
                "## Maintenance Receipt",
                f"- run_id: {run_id}",
                f"- source_message_refs: {', '.join(source_refs)}",
            ]
        )
        return "\n".join(lines).strip()

    def _assert_note_path_in_memory_dir(self, slug: str) -> None:
        notes_dir = (Path(self.memory_manager.root_dir) / "notes").resolve()
        target = self.memory_manager.note_path(slug).resolve()
        if target == notes_dir or notes_dir not in target.parents:
            raise ValueError("durable memory write target escapes notes directory")

    def _dedupe(self, items: list[str]) -> list[str]:
        result: list[str] = []
        for item in items:
            normalized = normalize_storage_text(item)
            if normalized and normalized not in result:
                result.append(normalized)
        return result


class MemoryMaintenanceCoordinator:
    """Coordinates agent:1 maintenance and sends all writes through MemoryCommitter."""

    def __init__(
        self,
        *,
        base_dir: Path,
        session_memory_layer: Any,
        memory_manager: Any,
        maintenance_agent: MemoryMaintenanceAgent,
        on_durable_saved: Callable[[int], None] | None = None,
    ) -> None:
        layout = ProjectLayout.from_backend_dir(base_dir)
        self.runtime_dir = layout.runtime_state_dir / "memory_maintenance"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.session_memory_layer = session_memory_layer
        self.memory_manager = memory_manager
        self.maintenance_agent = maintenance_agent
        self.committer = MemoryCommitter(
            session_memory_layer=session_memory_layer,
            memory_manager=memory_manager,
            on_durable_saved=on_durable_saved,
        )
        self._lock = threading.RLock()
        self._in_progress: set[str] = set()
        self._pending: dict[str, dict[str, Any]] = {}

    def set_durable_saved_callback(self, callback: Callable[[int], None] | None) -> None:
        self.committer.set_durable_saved_callback(callback)

    def describe_runtime_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "authority": "memory_system.maintenance_coordinator",
                "commit_authority": "memory_system.memory_committer",
                "agent_id": MEMORY_MANAGER_AGENT_ID,
                "active_session_count": len(self._in_progress),
                "pending_session_count": len(self._pending),
                "receipt_root": str(self.runtime_dir),
            }

    async def run_after_commit(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        turn_id: str = "",
        main_context: dict[str, Any] | None = None,
        task_summary_refs: list[dict[str, Any]] | None = None,
        bundle_summary_refs: list[dict[str, Any]] | None = None,
        durable_lane_enabled: bool = True,
    ) -> MemoryMaintenanceReceipt:
        safe_session_id = self._safe_session_id(session_id)
        message_count = len(messages or [])
        run_id = f"memory-maintenance:{safe_session_id}:{message_count}"
        queued = self._try_start_or_queue(
            safe_session_id,
            {
                "session_id": safe_session_id,
                "messages": list(messages or []),
                "turn_id": turn_id,
                "main_context": dict(main_context or {}),
                "task_summary_refs": list(task_summary_refs or []),
                "bundle_summary_refs": list(bundle_summary_refs or []),
                "durable_lane_enabled": durable_lane_enabled,
            },
        )
        if queued:
            receipt = MemoryMaintenanceReceipt(
                run_id=run_id,
                session_id=safe_session_id,
                turn_id=turn_id,
                status="queued",
                queued=True,
                durable_skipped=True,
                durable_skip_reason="maintenance_already_in_progress",
                processed_message_count=message_count,
            )
            return self._persist_receipt(receipt)

        try:
            state = self._load_state(safe_session_id)
            last_index = int(state.get("last_memory_message_index") or 0)
            if message_count <= last_index:
                receipt = MemoryMaintenanceReceipt(
                    run_id=run_id,
                    session_id=safe_session_id,
                    turn_id=turn_id,
                    status="skipped",
                    attempted=False,
                    durable_skipped=True,
                    durable_skip_reason="no_new_committed_messages",
                    last_memory_message_index=last_index,
                    processed_message_count=message_count,
                )
                return self._persist_receipt(receipt)

            request = self._build_request(
                run_id=run_id,
                session_id=safe_session_id,
                turn_id=turn_id,
                messages=messages,
                last_index=last_index,
                main_context=main_context or {},
                task_summary_refs=task_summary_refs or [],
                bundle_summary_refs=bundle_summary_refs or [],
                durable_lane_enabled=durable_lane_enabled,
            )
            self._update_runtime_state_projection(request)
            proposal = await self.maintenance_agent.maintain(request)
            receipt = self._commit_proposal(request, proposal)
            self._save_state(
                safe_session_id,
                {
                    "last_memory_message_index": message_count,
                    "last_run_id": receipt.run_id,
                    "last_status": receipt.status,
                    "updated_at": utc_now_iso(),
                },
            )
            receipt.last_memory_message_index = message_count
            receipt.processed_message_count = message_count
            return self._persist_receipt(receipt)
        except Exception as exc:
            receipt = MemoryMaintenanceReceipt(
                run_id=run_id,
                session_id=safe_session_id,
                turn_id=turn_id,
                status="failed",
                attempted=True,
                durable_memory_succeeded=False,
                durable_write_count=0,
                error=str(exc),
                processed_message_count=message_count,
            )
            return self._persist_receipt(receipt)
        finally:
            pending_payload = self._finish_and_take_pending(safe_session_id)
            if pending_payload:
                self._schedule_trailing_run(pending_payload)

    def run_after_commit_sync(self, **payload: Any) -> MemoryMaintenanceReceipt:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_after_commit(**payload))
        return MemoryMaintenanceReceipt(
            run_id=f"memory-maintenance:{self._safe_session_id(payload.get('session_id', ''))}:queued",
            session_id=self._safe_session_id(payload.get("session_id", "")),
            turn_id=str(payload.get("turn_id") or ""),
            status="queued",
            queued=True,
            durable_skipped=True,
            durable_skip_reason="sync_call_inside_running_loop",
            diagnostics={"reason": "use async memory maintenance entrypoint"},
        )

    def _build_request(
        self,
        *,
        run_id: str,
        session_id: str,
        turn_id: str,
        messages: list[dict[str, Any]],
        last_index: int,
        main_context: dict[str, Any],
        task_summary_refs: list[dict[str, Any]],
        bundle_summary_refs: list[dict[str, Any]],
        durable_lane_enabled: bool,
    ) -> MemoryMaintenanceRequest:
        start = max(0, last_index - 4)
        message_slice = [self._message_payload(index, item) for index, item in enumerate(messages[start:], start=start)][-16:]
        manager = self.session_memory_layer.manager(session_id)
        previous = manager.load()
        source_refs = [f"message:{index}" for index in range(last_index, len(messages))]
        headers = [
            {
                "note_id": header.note_id,
                "filename": header.filename,
                "memory_type": header.memory_type,
                "memory_class": header.memory_class,
                "title": header.title,
                "description": header.description,
                "status": header.status,
                "confidence": header.confidence,
                "eligible_for_injection": header.eligible_for_injection,
                "canonical_statement": header.canonical_statement,
                "summary": header.summary,
            }
            for header in scan_memory_headers(self.memory_manager.root_dir, limit=120)
        ]
        return MemoryMaintenanceRequest(
            run_id=run_id,
            session_id=session_id,
            turn_id=turn_id,
            message_count=len(messages),
            last_memory_message_index=last_index,
            message_slice=message_slice,
            previous_session_memory=previous[:20000],
            main_context=dict(main_context or {}),
            task_summary_refs=list(task_summary_refs or [])[:8],
            bundle_summary_refs=list(bundle_summary_refs or [])[:8],
            manifest_headers=headers,
            source_message_refs=source_refs,
            durable_lane_enabled=durable_lane_enabled,
        )

    def _commit_proposal(
        self,
        request: MemoryMaintenanceRequest,
        proposal: MemoryMaintenanceProposal,
    ) -> MemoryMaintenanceReceipt:
        commit = self.committer.commit(request, proposal)
        durable_error = str(commit.get("durable_error") or "")
        return MemoryMaintenanceReceipt(
            run_id=request.run_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            status="succeeded",
            attempted=True,
            session_memory_succeeded=bool(commit["session_memory_succeeded"]),
            durable_memory_succeeded=bool(commit["durable_memory_succeeded"]),
            durable_write_count=int(commit["durable_write_count"]),
            durable_skipped=bool(commit["durable_skipped"]),
            durable_skip_reason=str(commit["durable_skip_reason"]),
            diagnostics={
                **dict(proposal.diagnostics or {}),
                "commit_authority": "memory_system.memory_committer",
                "proposal_authority": proposal.authority,
                "durable_reasoning_summary": proposal.durable_memory.reasoning_summary,
                "durable_error": durable_error,
                "durable_actions": commit["durable_actions"],
            },
        )

    def _update_runtime_state_projection(self, request: MemoryMaintenanceRequest) -> None:
        if not (request.main_context or request.task_summary_refs or request.bundle_summary_refs):
            return
        self.session_memory_layer.update_runtime_state_from_context_state(
            request.session_id,
            dict(request.main_context or {}),
            task_summaries=list(request.task_summary_refs or []),
            bundle_summaries=list(request.bundle_summary_refs or []),
            corrections=[],
        )

    def _message_payload(self, index: int, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "message_ref": f"message:{index}",
            "role": str(item.get("role") or ""),
            "content": str(item.get("content") or "")[:6000],
            "answer_source": str(item.get("answer_source") or ""),
            "answer_channel": str(item.get("answer_channel") or ""),
        }

    def _try_start_or_queue(self, session_id: str, payload: dict[str, Any]) -> bool:
        with self._lock:
            if session_id in self._in_progress:
                self._pending[session_id] = payload
                return True
            self._in_progress.add(session_id)
            return False

    def _finish_and_take_pending(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._in_progress.discard(session_id)
            return self._pending.pop(session_id, None)

    def _schedule_trailing_run(self, payload: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.run_after_commit(**payload))

    def _session_dir(self, session_id: str) -> Path:
        safe = safe_runtime_session_key(session_id)
        path = self.runtime_dir / safe
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _load_state(self, session_id: str) -> dict[str, Any]:
        path = self._session_dir(session_id) / "state.json"
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Memory maintenance runtime state must be a JSON object")
        return payload

    def _save_state(self, session_id: str, payload: dict[str, Any]) -> None:
        path = self._session_dir(session_id) / "state.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _persist_receipt(self, receipt: MemoryMaintenanceReceipt) -> MemoryMaintenanceReceipt:
        path = self._session_dir(receipt.session_id) / f"{receipt.run_id.replace(':', '_')}.json"
        receipt.receipt_path = str(path)
        path.write_text(json.dumps(receipt.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return receipt

    def _safe_session_id(self, session_id: Any) -> str:
        return normalize_session_id(session_id)


