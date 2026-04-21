from __future__ import annotations

from typing import Any

from context_management import ContextControllerResult, ContextPackage
from structured_memory import Message

from memory.durable import DurableMemoryLayer
from memory.session import SessionMemoryLayer


class MemoryContextLayer:
    def __init__(
        self,
        session_memory: SessionMemoryLayer,
        durable_memory: DurableMemoryLayer,
    ) -> None:
        self.session_memory = session_memory
        self.durable_memory = durable_memory

    def build_session_memory_block(
        self,
        session_id: str,
        *,
        history: list[Message] | None = None,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        relevant_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        include_durable_context: bool = True,
    ) -> str:
        package = self.build_context_package(
            session_id,
            history=history,
            pending_user_message=pending_user_message,
            memory_intent=memory_intent,
            relevant_notes=relevant_notes,
            retrieval_results=retrieval_results,
            rebuild_reason="prompt_assembly",
        )
        return self._render_context_package_block(
            package,
            include_durable_context=include_durable_context,
            mode="model",
        )

    def build_context_package(
        self,
        session_id: str,
        *,
        history: list[Message] | None = None,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        relevant_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        rebuild_reason: str = "prompt_assembly",
    ) -> ContextPackage:
        exact_matches = self.durable_memory.find_exact_matches(
            pending_user_message,
            memory_intent,
            note_limit=5,
        )
        relevant_payload = [
            {
                "filename": getattr(note, "filename", ""),
                "title": getattr(note, "title", ""),
                "memory_type": getattr(note, "memory_type", ""),
                "memory_class": getattr(note, "memory_class", ""),
            }
            for note in (relevant_notes or [])
        ]
        exact_payload = [
            {
                "filename": match.filename,
                "title": match.title,
                "memory_type": match.memory_type,
                "memory_class": match.memory_class,
            }
            for match in exact_matches
        ]
        retrieval_payload = self._retrieval_items_from_results(retrieval_results)
        controller = self.session_memory.context_controller(session_id)
        return controller.build_context_package(
            list(history or []),
            rebuild_reason=rebuild_reason,
            pending_user_message=pending_user_message,
            exact_durable_matches=exact_payload,
            relevant_durable_matches=relevant_payload,
            retrieval_evidence=retrieval_payload,
        )

    def inspect_query_context(
        self,
        session_id: str,
        *,
        history: list[Message] | None = None,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        relevant_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        note_limit: int = 5,
        context_compaction: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        manager = self.session_memory.manager(session_id)
        package = self.build_context_package(
            session_id,
            history=history,
            pending_user_message=pending_user_message,
            memory_intent=memory_intent,
            relevant_notes=relevant_notes,
            retrieval_results=retrieval_results,
            rebuild_reason="inspect_query_context",
        )
        model_session_summary = self._render_context_package_block(
            package,
            include_durable_context=False,
            mode="model",
        )
        debug_session_summary = self._render_context_package_block(
            package,
            include_durable_context=False,
            mode="debug",
        )
        preview_history = list(history or [])
        if pending_user_message:
            preview_history.append(Message(role="user", content=pending_user_message))
        if preview_history:
            session_state = manager.preview_state(preview_history)
        else:
            session_state = manager.load_state()
        exact_matches = self.durable_memory.find_exact_matches(
            pending_user_message,
            memory_intent,
            note_limit=note_limit,
        )
        exact_filenames = {match.filename for match in exact_matches}
        surfaced_relevant_notes = [
            note
            for note in (relevant_notes or [])
            if getattr(note, "filename", "") not in exact_filenames
        ]
        return {
            "memory_intent": {
                "intent": getattr(memory_intent, "intent", "general"),
                "read_mode": getattr(memory_intent, "memory_read_mode", "none"),
                "write_mode": getattr(memory_intent, "memory_write_mode", "none"),
                "preferred_types": list(getattr(memory_intent, "preferred_types", []) or []),
                "preferred_memory_classes": list(
                    getattr(memory_intent, "preferred_memory_classes", []) or []
                ),
            },
            "session_memory": {
                "present": bool(model_session_summary.strip()),
                "preview": debug_session_summary[:600].strip(),
                "model_preview": model_session_summary[:600].strip(),
                "storage": manager.describe_storage(),
                "model_visible": {
                    "preview": model_session_summary[:600].strip(),
                    "context_slots": {
                        "active_pdf": session_state.context_slots.active_pdf,
                        "active_dataset": session_state.context_slots.active_dataset,
                        "active_entity": session_state.context_slots.active_entity,
                    },
                },
                "debug_visible": {
                    "preview": debug_session_summary[:600].strip(),
                    "context_slots": {
                        "active_pdf": session_state.context_slots.active_pdf,
                        "active_dataset": session_state.context_slots.active_dataset,
                        "active_entity": session_state.context_slots.active_entity,
                        "active_rule": session_state.context_slots.active_rule,
                    },
                },
                "active_goal": session_state.active_goal,
                "flow_state": {
                    "flow_id": session_state.flow_state.flow_id,
                    "flow_type": session_state.flow_state.flow_type,
                    "status": session_state.flow_state.status,
                    "confidence": session_state.flow_state.confidence,
                },
                "task_state": {
                    "current_step": session_state.task_state.current_step,
                    "completed_steps": list(session_state.task_state.completed_steps),
                    "pending_steps": list(session_state.task_state.pending_steps),
                    "next_step": session_state.task_state.next_step,
                },
                "context_slots": {
                    "active_pdf": session_state.context_slots.active_pdf,
                    "active_dataset": session_state.context_slots.active_dataset,
                    "active_entity": session_state.context_slots.active_entity,
                    "active_rule": session_state.context_slots.active_rule,
                },
                "risk": {
                    "flags": list(session_state.risk_flags),
                    "notes": list(session_state.risk_notes),
                    "has_risk": bool(session_state.risk_flags),
                },
                "warm_snapshots": [
                    {
                        "flow_id": snapshot.flow_id,
                        "flow_type": snapshot.flow_type,
                        "goal": snapshot.goal,
                        "resume_hints": list(snapshot.resume_hints),
                    }
                    for snapshot in manager.load_flow_snapshots()
                ],
            },
            "durable_memory": {
                "exact_matches": [
                    {
                        "filename": match.filename,
                        "title": match.title,
                        "memory_type": match.memory_type,
                        "memory_class": match.memory_class,
                        "schema_version": getattr(match, "schema_version", "durable-memory.v2"),
                        "confidence": getattr(match, "confidence", ""),
                        "score": round(match.score, 2),
                    }
                    for match in exact_matches
                ],
                "relevant_notes": [
                    {
                        "filename": getattr(note, "filename", ""),
                        "title": getattr(note, "title", ""),
                        "memory_type": getattr(note, "memory_type", ""),
                        "memory_class": getattr(note, "memory_class", ""),
                        "schema_version": getattr(note, "schema_version", "durable-memory.v2"),
                        "confidence": getattr(note, "confidence", ""),
                    }
                    for note in surfaced_relevant_notes[:note_limit]
                ],
                "extraction_runtime": self.durable_memory.describe_extraction_runtime(),
            },
            "context_management": context_compaction
            or {
                "pressure_level": "unknown",
                "strategy": "unknown",
                "did_compact": False,
                "did_microcompact": False,
                "did_full_compact": False,
            },
        }

    def compact_history_for_query(
        self,
        session_id: str,
        history: list[Message],
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        controller_result = self.session_memory.context_controller(session_id).compact_history(history)
        compacted = [
            {"role": message.role, "content": message.content}
            for message in controller_result.messages
        ]
        return compacted, self._compact_trace(controller_result)

    def _render_context_package_block(
        self,
        package: ContextPackage,
        *,
        include_durable_context: bool = True,
        mode: str = "model",
    ) -> str:
        section_order = [
            ("active_process_context", None),
            ("hot_truth_window", "## Hot Truth Window"),
            ("retrieval_evidence", "## Retrieval Evidence"),
            ("warm_snapshots", "## Warm Flow Snapshots"),
            ("exact_durable_context", "## Exact Durable Context"),
            ("relevant_durable_context", "## Relevant Durable Context"),
            ("debug_session_trace", "## Debug Session Trace"),
        ]
        lines: list[str] = []
        sections = self._sections_for_package(package, mode=mode)
        for section_name, heading in section_order:
            if not include_durable_context and section_name in {
                "exact_durable_context",
                "relevant_durable_context",
            }:
                continue
            if mode != "debug" and section_name == "debug_session_trace":
                continue
            items = list(sections.get(section_name, []))
            if not items:
                continue
            if heading is not None:
                if lines:
                    lines.append("")
                lines.append(heading)
            for item in items:
                stripped = str(item).strip()
                if not stripped:
                    continue
                if section_name in {"active_process_context", "debug_session_trace"}:
                    if lines:
                        lines.append("")
                    lines.append(stripped)
                else:
                    lines.append(f"- {stripped}")
        return "\n".join(lines).strip()

    def _sections_for_package(
        self,
        package: ContextPackage,
        *,
        mode: str,
    ) -> dict[str, list[str]]:
        if hasattr(package, "sections_for"):
            return package.sections_for("debug" if mode == "debug" else "model")
        if mode == "debug" and hasattr(package, "debug_sections"):
            return getattr(package, "debug_sections")
        if hasattr(package, "model_visible_sections"):
            return getattr(package, "model_visible_sections")
        return package.sections

    def _retrieval_items_from_results(
        self,
        retrieval_results: list[dict[str, Any]] | None,
    ) -> list[str]:
        items: list[str] = []
        for item in retrieval_results or []:
            source = str(item.get("source", "") or "").strip()
            text = str(item.get("text", "") or "").strip()
            collection = str(item.get("collection", "") or "").strip()
            prefix_parts = [part for part in (source, collection) if part]
            prefix = " | ".join(prefix_parts)
            if prefix and text:
                items.append(f"{prefix}: {text}")
            elif text:
                items.append(text)
        return items

    def _compact_trace(self, result: ContextControllerResult) -> dict[str, Any]:
        compact = result.compact_result
        package = result.package
        trace = package.to_dict()
        trace.update(
            {
                "pressure_level": compact.pressure_level,
                "strategy": compact.strategy,
                "did_compact": compact.did_compact,
                "did_microcompact": compact.did_microcompact,
                "did_full_compact": compact.did_full_compact,
                "estimated_tokens_before": compact.estimated_tokens_before,
                "estimated_tokens_after": compact.estimated_tokens_after,
                "original_message_count": compact.original_message_count,
                "compacted_message_count": compact.compacted_message_count,
                "replaced_message_count": compact.replaced_message_count,
                "preserved_recent_count": compact.preserved_recent_count,
            }
        )
        return trace
