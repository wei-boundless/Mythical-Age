from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, Callable

from project_layout import ProjectLayout
from memory_system.storage.models import MemoryNote
from memory_system.storage.text_utils import normalize_storage_text

from .maintenance_agent import MemoryMaintenanceAgent
from .maintenance_models import (
    ALLOWED_DURABLE_MEMORY_CLASSES,
    ALLOWED_DURABLE_MEMORY_TYPES,
    MEMORY_MANAGER_AGENT_ID,
    MemoryMaintenanceReceipt,
    MemoryMaintenanceRequest,
    MemoryMaintenanceResult,
    utc_now_iso,
)
from .manifest_scan import scan_memory_headers
from .paths import normalize_session_id, safe_runtime_session_key


class MemoryMaintenanceCoordinator:
    """Coordinates agent:1 memory maintenance after assistant commits."""

    def __init__(
        self,
        *,
        base_dir: Path,
        session_memory_layer: Any,
        memory_manager: Any,
        maintenance_agent: MemoryMaintenanceAgent,
        on_durable_saved: Callable[[int], None] | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        layout = ProjectLayout.from_backend_dir(base_dir)
        self.runtime_dir = layout.runtime_state_dir / "memory_maintenance"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.session_memory_layer = session_memory_layer
        self.memory_manager = memory_manager
        self.maintenance_agent = maintenance_agent
        self.on_durable_saved = on_durable_saved
        self._lock = threading.RLock()
        self._in_progress: set[str] = set()
        self._pending: dict[str, dict[str, Any]] = {}

    def set_durable_saved_callback(self, callback: Callable[[int], None] | None) -> None:
        self.on_durable_saved = callback

    def describe_runtime_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "authority": "memory_system.maintenance_coordinator",
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
            result = await self.maintenance_agent.maintain(request)
            receipt = self._apply_result(request, result)
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
        message_slice = [
            self._message_payload(index, item)
            for index, item in enumerate(messages[max(0, last_index - 4) :], start=max(0, last_index - 4))
        ][-16:]
        manager = self.session_memory_layer.manager(session_id)
        previous = ""
        try:
            previous = manager.load()
        except Exception:
            previous = ""
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

    def _apply_result(
        self,
        request: MemoryMaintenanceRequest,
        result: MemoryMaintenanceResult,
    ) -> MemoryMaintenanceReceipt:
        if result.session_memory.is_empty():
            raise ValueError("memory maintenance agent returned empty session memory")
        manager = self.session_memory_layer.manager(request.session_id)
        manager.overwrite(
            result.session_memory.render_markdown(),
            debug_content=result.session_memory.render_markdown(),
        )
        durable_count = 0
        durable_skipped = True
        durable_skip_reason = ""
        durable_error = ""
        durable_actions = {"created": [], "updated": [], "merged": [], "deprecated": [], "rejected": []}
        if not request.durable_lane_enabled:
            durable_skip_reason = "durable_lane_disabled"
        else:
            try:
                actions = result.durable_memory.normalized_actions()
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
                    durable_skip_reason = result.durable_memory.skipped_reason or "agent_returned_no_durable_actions"
            except Exception as exc:
                durable_skipped = True
                durable_error = str(exc)
                durable_actions["rejected"].append(durable_error)
                durable_skip_reason = "durable_write_rejected_by_sandbox"
        return MemoryMaintenanceReceipt(
            run_id=request.run_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            status="succeeded",
            attempted=True,
            session_memory_succeeded=True,
            durable_memory_succeeded=bool(request.durable_lane_enabled and not durable_error),
            durable_write_count=durable_count,
            durable_skipped=durable_skipped,
            durable_skip_reason=durable_skip_reason,
            diagnostics={
                **dict(result.diagnostics or {}),
                "durable_reasoning_summary": result.durable_memory.reasoning_summary,
                "durable_error": durable_error,
                "durable_actions": durable_actions,
            },
        )

    def _apply_durable_action(self, action: Any, *, request: MemoryMaintenanceRequest) -> dict[str, list[str]]:
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
            merge_ids = [self.memory_manager.slugify(item) for item in list(action.merge_note_ids or []) if str(item or "").strip()]
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
            )
            return {"merged": [target], "deprecated": deprecated}
        raise ValueError(f"unsupported durable memory action: {action.action}")

    def _update_runtime_state_projection(self, request: MemoryMaintenanceRequest) -> None:
        if not (request.main_context or request.task_summary_refs or request.bundle_summary_refs):
            return
        updater = getattr(self.session_memory_layer, "update_runtime_state_from_context_state", None)
        if not callable(updater):
            return
        updater(
            request.session_id,
            dict(request.main_context or {}),
            task_summaries=list(request.task_summary_refs or []),
            bundle_summaries=list(request.bundle_summary_refs or []),
            corrections=[],
        )

    def _note_from_action(self, action: Any, *, request: MemoryMaintenanceRequest) -> MemoryNote:
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
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

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

    def _dedupe(self, items: list[str]) -> list[str]:
        result: list[str] = []
        for item in items:
            normalized = normalize_storage_text(item)
            if normalized and normalized not in result:
                result.append(normalized)
        return result

