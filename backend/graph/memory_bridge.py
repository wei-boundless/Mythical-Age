from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from context_management import ContextController, ContextControllerResult, ContextPackage
from structured_memory import (
    ExactMemoryMatch,
    ExtractionConfig,
    ExtractionScheduler,
    MemoryExtractor,
    MemoryManager,
    Message,
    SessionMemoryManager,
    find_exact_memory_matches,
)


class GraphMemoryBridge:
    """Adapts structured_memory components to the graph runtime."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.memory_manager = MemoryManager(base_dir / "durable_memory")
        self.extractor = MemoryExtractor(self.memory_manager)
        self.scheduler = ExtractionScheduler(
            self.extractor,
            config=ExtractionConfig(min_messages_between_runs=4),
        )
        self.session_root = base_dir / "session-memory"
        self.session_root.mkdir(parents=True, exist_ok=True)

    def _session_dir(self, session_id: str) -> Path:
        return self.session_root / session_id

    def _session_memory(self, session_id: str) -> SessionMemoryManager:
        return SessionMemoryManager(self._session_dir(session_id))

    def _compactor(self, session_id: str):
        from context_management import ContextCompactor

        return ContextCompactor(self._session_memory(session_id))

    def _context_controller(self, session_id: str) -> ContextController:
        controller = ContextController(self._session_memory(session_id))
        override_compactor = getattr(self, "_compactor", None)
        if callable(override_compactor):
            controller.compactor = override_compactor(session_id)
        return controller

    def _looks_like_skill_document(self, content: str) -> bool:
        normalized = content.strip()
        if not normalized:
            return False
        lowered = normalized.lower()
        if "skills/" in lowered and "/skill.md" in lowered:
            return True
        has_skill_frontmatter = (
            (normalized.startswith("---") or lowered.startswith("name:"))
            and "metadata:" in lowered
            and "description:" in lowered
        )
        heading_hits = sum(
            1
            for marker in (
                "## execution steps",
                "## lessons learned",
                "## troubleshooting",
                "## output format",
                "目标",
                "执行步骤",
                "输出格式",
                "故障排查",
                "查询策略",
            )
            if marker in normalized or marker in lowered
        )
        if has_skill_frontmatter and heading_hits >= 1:
            return True
        if "display_name:" in lowered and heading_hits >= 1:
            return True
        return False

    def _should_skip_memory_message(self, role: str, content: str) -> bool:
        if role == "tool":
            return self._looks_like_skill_document(content)
        if role == "assistant" and self._looks_like_skill_document(content):
            return True
        return False

    def _to_py_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        session_id: str | None = None,
    ) -> list[Message]:
        converted: list[Message] = []
        for item in messages:
            role = str(item.get("role", "") or "")
            if role not in {"system", "user", "assistant", "tool"}:
                continue
            content = str(item.get("content", "") or "")
            if self._should_skip_memory_message(role, content):
                continue
            meta = dict(item.get("meta", {}) or {})
            if session_id:
                meta["session_id"] = session_id
            converted.append(Message(role=role, content=content, meta=meta))
        return converted

    def refresh_session_memory(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> str:
        manager = self._session_memory(session_id)
        return manager.update_from_messages(self._to_py_messages(messages, session_id=session_id))

    def build_session_memory_block(
        self,
        session_id: str,
        history: list[dict[str, Any]] | None = None,
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
        )

    def build_context_package(
        self,
        session_id: str,
        *,
        history: list[dict[str, Any]] | None = None,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        relevant_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        rebuild_reason: str = "prompt_assembly",
    ) -> ContextPackage:
        py_history = self._to_py_messages(history or [], session_id=session_id)
        exact_matches = self._find_exact_matches(
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
        controller = self._context_controller(session_id)
        return controller.build_context_package(
            py_history,
            rebuild_reason=rebuild_reason,
            pending_user_message=pending_user_message,
            exact_durable_matches=exact_payload,
            relevant_durable_matches=relevant_payload,
            retrieval_evidence=retrieval_payload,
        )

    def build_persistent_memory_block(
        self,
        query: str | None = None,
        memory_intent: Any | None = None,
        note_limit: int = 5,
        relevant_notes: list[Any] | None = None,
    ) -> str:
        self.memory_manager.ensure_index_consistent()
        sections: list[str] = []
        exact_matches = self._find_exact_matches(query, memory_intent, note_limit=note_limit)

        if exact_matches:
            sections.append("## Exact Durable Memory Matches")
            for match in exact_matches:
                sections.extend(
                    [
                        "",
                        f"### {match.title}",
                        f"Schema: {getattr(match, 'schema_version', 'durable-memory.v2')}",
                        f"Memory Class: {match.memory_class}",
                        f"Type: {match.memory_type}",
                    ]
                )
                if match.summary:
                    sections.append(f"Summary: {match.summary}")
                if getattr(match, "canonical_statement", ""):
                    sections.append(f"Canonical: {getattr(match, 'canonical_statement', '')}")
                if match.tags:
                    sections.append(f"Tags: {', '.join(match.tags)}")
                if getattr(match, "retrieval_hints", []):
                    sections.append(f"Retrieval Hints: {', '.join(getattr(match, 'retrieval_hints', []))}")
                if getattr(match, "confidence", ""):
                    sections.append(f"Confidence: {getattr(match, 'confidence', '')}")
                if getattr(match, "created_by", ""):
                    sections.append(f"Created By: {getattr(match, 'created_by', '')}")
                if getattr(match, "source_message_excerpt", ""):
                    sections.append(f"Source: {getattr(match, 'source_message_excerpt', '')}")
                sections.append(match.body.strip())

        index_text = self.memory_manager.load_index().strip()
        if index_text:
            if sections:
                sections.append("")
            sections.extend(["## Persistent Memory Index", index_text])

        manifest = self.memory_manager.build_manifest(limit=note_limit).strip()
        if manifest:
            sections.extend(["", "## Persistent Memory Manifest", manifest])

        exact_filenames = {match.filename for match in exact_matches}
        surfaced_relevant_notes = [
            note
            for note in (relevant_notes or [])
            if getattr(note, "filename", "") not in exact_filenames
        ]
        if surfaced_relevant_notes:
            sections.append("")
            sections.append("## Relevant Durable Memories")
            for note in surfaced_relevant_notes:
                sections.extend(
                    [
                        "",
                        f"### {note.title}",
                        f"Schema: {getattr(note, 'schema_version', 'durable-memory.v2')}",
                        f"Memory Class: {note.memory_class}",
                        f"Type: {note.memory_type}",
                    ]
                )
                if note.summary:
                    sections.append(f"Summary: {note.summary}")
                if getattr(note, "canonical_statement", ""):
                    sections.append(f"Canonical: {getattr(note, 'canonical_statement', '')}")
                if getattr(note, "retrieval_hints", []):
                    sections.append(f"Retrieval Hints: {', '.join(getattr(note, 'retrieval_hints', []))}")
                if getattr(note, "confidence", ""):
                    sections.append(f"Confidence: {getattr(note, 'confidence', '')}")
                if getattr(note, "created_by", ""):
                    sections.append(f"Created By: {getattr(note, 'created_by', '')}")
                if getattr(note, "source_message_excerpt", ""):
                    sections.append(f"Source: {getattr(note, 'source_message_excerpt', '')}")
                sections.append(note.content.strip())

        if exact_matches:
            notes = [self.memory_manager.load_note(Path(match.filename).stem) for match in exact_matches]
            note_blocks = [note.strip() for note in notes if note]
            if note_blocks:
                sections.append("")
                sections.append("## Loaded Memory Notes")
                for block in note_blocks:
                    sections.append("")
                    sections.append(block)
                return "\n".join(sections).strip()

        notes = [] if surfaced_relevant_notes else self.memory_manager.load_relevant_notes(limit=note_limit)
        if notes:
            sections.append("")
            sections.append("## Loaded Memory Notes")
            for note in notes:
                sections.extend(
                    [
                        "",
                        f"### {note.title}",
                        f"Schema: {getattr(note, 'schema_version', 'durable-memory.v2')}",
                        f"Memory Class: {note.memory_class}",
                        f"Type: {note.memory_type}",
                    ]
                )
                if note.summary:
                    sections.append(f"Summary: {note.summary}")
                if getattr(note, "canonical_statement", ""):
                    sections.append(f"Canonical: {getattr(note, 'canonical_statement', '')}")
                if getattr(note, "retrieval_hints", []):
                    sections.append(f"Retrieval Hints: {', '.join(getattr(note, 'retrieval_hints', []))}")
                if getattr(note, "confidence", ""):
                    sections.append(f"Confidence: {getattr(note, 'confidence', '')}")
                if getattr(note, "created_by", ""):
                    sections.append(f"Created By: {getattr(note, 'created_by', '')}")
                if getattr(note, "source_message_excerpt", ""):
                    sections.append(f"Source: {getattr(note, 'source_message_excerpt', '')}")
                sections.append(note.content.strip())

        return "\n".join(sections).strip()

    def inspect_memory_context(
        self,
        session_id: str,
        *,
        history: list[dict[str, Any]] | None = None,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        relevant_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        note_limit: int = 5,
        context_compaction: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        manager = self._session_memory(session_id)
        session_summary = self.build_session_memory_block(
            session_id,
            history=history,
            pending_user_message=pending_user_message,
            memory_intent=memory_intent,
            relevant_notes=relevant_notes,
            retrieval_results=retrieval_results,
            include_durable_context=False,
        )
        preview_history = list(history or [])
        if pending_user_message:
            preview_history.append({"role": "user", "content": pending_user_message})
        if preview_history:
            session_state = manager.preview_state(
                self._to_py_messages(preview_history, session_id=session_id)
            )
        else:
            session_state = manager.load_state()
        exact_matches = self._find_exact_matches(
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
                "present": bool(session_summary.strip()),
                "preview": session_summary[:600].strip(),
                "storage": manager.describe_storage(),
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

    def prefetch_relevant_notes(
        self,
        query: str,
        memory_intent: Any | None = None,
        *,
        limit: int = 3,
    ) -> list[Any]:
        preferred_types = list(getattr(memory_intent, "preferred_types", []) or [])
        preferred_classes = list(getattr(memory_intent, "preferred_memory_classes", []) or [])
        if not preferred_classes:
            preferred_classes = self._infer_relevant_classes(query, preferred_types)
        return self.memory_manager.select_relevant_notes(
            query,
            preferred_types=preferred_types,
            preferred_classes=preferred_classes,
            limit=limit,
        )

    def _infer_relevant_classes(
        self,
        query: str,
        preferred_types: list[str],
    ) -> list[str]:
        lowered = (query or "").lower()
        preferred: list[str] = []

        if any(item in {"preference", "user"} for item in preferred_types):
            preferred.append("preference")
        if any(item in {"project", "workflow", "reference"} for item in preferred_types):
            preferred.append("work")

        if any(marker in lowered for marker in ("喜欢", "偏好", "习惯", "风格", "要求", "默认")):
            preferred.append("preference")
        if any(marker in lowered for marker in ("项目", "架构", "流程", "工作流", "重点", "约定", "规范")):
            preferred.append("work")

        if not preferred:
            return ["work", "preference"]

        deduped: list[str] = []
        for item in preferred:
            if item not in deduped:
                deduped.append(item)
        return deduped

    def _find_exact_matches(
        self,
        query: str | None,
        memory_intent: Any | None,
        *,
        note_limit: int,
    ) -> list[ExactMemoryMatch]:
        if (
            not query
            or memory_intent is None
            or getattr(memory_intent, "memory_read_mode", "none") != "durable_exact"
        ):
            return []
        return find_exact_memory_matches(
            self.memory_manager.root_dir,
            query,
            preferred_types=list(getattr(memory_intent, "preferred_types", []) or []),
            limit=min(3, note_limit),
        )

    def compact_history_for_agent(
        self,
        session_id: str,
        history: list[dict[str, Any]],
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        py_messages = self._to_py_messages(history)
        controller_result = self._context_controller(session_id).compact_history(py_messages)
        compacted = [{"role": message.role, "content": message.content} for message in controller_result.messages]
        return compacted, self._compact_trace(controller_result)

    def _render_context_package_block(
        self,
        package: ContextPackage,
        *,
        include_durable_context: bool = True,
    ) -> str:
        section_order = [
            ("active_process_context", None),
            ("hot_truth_window", "## Hot Truth Window"),
            ("retrieval_evidence", "## Retrieval Evidence"),
            ("warm_snapshots", "## Warm Flow Snapshots"),
            ("exact_durable_context", "## Exact Durable Context"),
            ("relevant_durable_context", "## Relevant Durable Context"),
        ]
        lines: list[str] = []
        for section_name, heading in section_order:
            if not include_durable_context and section_name in {
                "exact_durable_context",
                "relevant_durable_context",
            }:
                continue
            items = list(package.sections.get(section_name, []))
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
                if section_name == "active_process_context":
                    if lines:
                        lines.append("")
                    lines.append(stripped)
                else:
                    lines.append(f"- {stripped}")
        return "\n".join(lines).strip()

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

    def extract_durable_memories(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> int:
        notes = self.extractor.save_extracted(self._to_py_messages(messages, session_id=session_id))
        return len(notes)

    def set_durable_memory_saved_callback(self, callback: Callable[[int], None]) -> None:
        self.scheduler.on_saved = callback

    def submit_durable_memory_extraction(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> int:
        return self.scheduler.submit(self._to_py_messages(messages, session_id=session_id))
