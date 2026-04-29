from __future__ import annotations

import logging
import re
import threading
from typing import Any, Callable

from query.models import QueryExecutionPlan

logger = logging.getLogger(__name__)


class RuntimeContextState:
    def __init__(
        self,
        *,
        memory_facade,
        session_memory_projection: dict[str, dict[str, Any]],
        normalize_pdf_scope: Callable[[str], str],
    ) -> None:
        self.memory_facade = memory_facade
        self._session_memory_projection = session_memory_projection
        self._normalize_pdf_scope = normalize_pdf_scope
        self._projection_lock = threading.Lock()

    def capture_session_memory_projection(
        self,
        session_id: str,
        *,
        main_context_payload: Any,
        task_summary_payloads: Any,
    ) -> None:
        projection = self._build_projection_payload(
            main_context_payload=main_context_payload,
            task_summary_payloads=task_summary_payloads,
        )
        with self._projection_lock:
            existing = self._session_memory_projection.get(session_id)
            queued = self._legacy_or_queued_projections(existing)
            queued.append(projection)
            self._session_memory_projection[session_id] = {
                **projection,
                "durable_projection_queue": queued,
            }

    def peek_session_memory_projection(self, session_id: str) -> dict[str, Any] | None:
        with self._projection_lock:
            payload = self._session_memory_projection.get(session_id)
            if not isinstance(payload, dict):
                return None
            return {
                "main_context": payload.get("main_context"),
                "task_summary_refs": list(payload.get("task_summary_refs", []) or []),
                "corrections": list(payload.get("corrections", []) or []),
            }

    def pending_durable_projection_count(self, session_id: str) -> int:
        with self._projection_lock:
            payload = self._session_memory_projection.get(session_id)
            return len(self._legacy_or_queued_projections(payload))

    def peek_durable_memory_projections(self, session_id: str) -> list[dict[str, Any]]:
        with self._projection_lock:
            payload = self._session_memory_projection.get(session_id)
            return self._legacy_or_queued_projections(payload)

    def drain_durable_memory_projections(self, session_id: str) -> list[dict[str, Any]]:
        with self._projection_lock:
            payload = self._session_memory_projection.pop(session_id, None)
        return self._legacy_or_queued_projections(payload)

    def _build_projection_payload(
        self,
        *,
        main_context_payload: Any,
        task_summary_payloads: Any,
    ) -> dict[str, Any]:
        corrections: list[str] = []
        if isinstance(main_context_payload, dict):
            latest_correction = str(main_context_payload.get("latest_correction", "") or "").strip()
            if latest_correction:
                corrections.append(latest_correction)
        task_summaries = task_summary_payloads if isinstance(task_summary_payloads, list) else []
        return {
            "main_context": main_context_payload,
            "task_summary_refs": task_summaries,
            "corrections": corrections,
        }

    def _legacy_or_queued_projections(self, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        queued = payload.get("durable_projection_queue")
        if isinstance(queued, list) and queued:
            normalized: list[dict[str, Any]] = []
            for item in queued:
                if not isinstance(item, dict):
                    continue
                normalized.append(
                    {
                        "main_context": item.get("main_context"),
                        "task_summary_refs": list(item.get("task_summary_refs", []) or []),
                        "corrections": list(item.get("corrections", []) or []),
                    }
                )
            if normalized:
                return normalized
        return [
            {
                "main_context": payload.get("main_context"),
                "task_summary_refs": list(payload.get("task_summary_refs", []) or []),
                "corrections": list(payload.get("corrections", []) or []),
            }
        ]

    def load_state_memory_snapshot(self, session_id: str):
        loader = getattr(self.memory_facade, "build_state_memory_snapshot", None)
        if not callable(loader):
            return None
        try:
            return loader(session_id)
        except Exception:
            logger.exception("Failed to load StateMemory snapshot for %s", session_id)
            return None

    def load_state_memory_restore_candidate_contracts(self, session_id: str) -> tuple[Any, ...]:
        loader = getattr(self.memory_facade, "build_state_memory_restore_candidates", None)
        if not callable(loader):
            return ()
        try:
            return tuple(loader(session_id) or ())
        except Exception:
            logger.exception("Failed to load StateMemory restore candidates for %s", session_id)
            return ()

    def load_session_binding_snapshot(self, session_id: str) -> dict[str, Any]:
        state_snapshot = self.load_state_memory_snapshot(session_id)
        if state_snapshot is not None:
            slots = dict(getattr(state_snapshot, "context_slots", {}) or {})
            committed_pdf = str(slots.get("committed_pdf", "") or slots.get("active_pdf", "") or "").strip()
            committed_dataset = str(
                slots.get("committed_dataset", "") or slots.get("active_dataset", "") or ""
            ).strip()
            return {
                "committed_pdf": committed_pdf,
                "committed_pdf_owner_task_id": str(
                    slots.get("committed_pdf_owner_task_id", "")
                    or (slots.get("active_binding_owner_task_id", "") if committed_pdf else "")
                    or ""
                ).strip(),
                "committed_dataset": committed_dataset,
                "committed_dataset_owner_task_id": str(
                    slots.get("committed_dataset_owner_task_id", "")
                    or (slots.get("active_binding_owner_task_id", "") if committed_dataset else "")
                    or ""
                ).strip(),
                "active_object_handle_id": str(slots.get("active_object_handle_id", "") or "").strip(),
                "active_result_handle_id": str(slots.get("active_result_handle_id", "") or "").strip(),
                "active_subset_handle_id": str(slots.get("active_subset_handle_id", "") or "").strip(),
            }
        return {}

    def load_session_restore_candidates(self, session_id: str) -> dict[str, Any]:
        candidates: dict[str, Any] = {}
        restore_contracts = self.load_state_memory_restore_candidate_contracts(session_id)
        for contract in restore_contracts:
            if str(getattr(contract, "authority", "") or "") != "candidate_only":
                continue
            if bool(getattr(contract, "can_promote_to_current_fact", False)):
                continue
            restore_kind = str(getattr(contract, "restore_kind", "") or "")
            metadata = dict(getattr(contract, "metadata", {}) or {})
            value = getattr(contract, "value", "")
            if restore_kind == "context_slot":
                slot_name = str(metadata.get("slot_name", "") or "").strip()
                if slot_name in {"committed_pdf", "active_pdf"}:
                    candidates.setdefault("active_pdf", str(value or "").strip())
                elif slot_name in {"committed_dataset", "active_dataset"}:
                    candidates.setdefault("active_dataset", str(value or "").strip())
            elif restore_kind == "result_handle":
                handle_name = str(metadata.get("handle_name", "") or "").strip()
                if handle_name in {"active_object_handle_id", "active_result_handle_id", "active_subset_handle_id"}:
                    candidates.setdefault(handle_name, str(value or "").strip())
        candidates = {
            key: value
            for key, value in candidates.items()
            if str(value or "").strip()
        }
        if candidates:
            return candidates

        snapshot = self.load_session_binding_snapshot(session_id)
        committed_pdf = str(snapshot.get("committed_pdf", "") or "").strip()
        if committed_pdf:
            candidates["active_pdf"] = committed_pdf
        committed_dataset = str(snapshot.get("committed_dataset", "") or "").strip()
        if committed_dataset:
            candidates["active_dataset"] = committed_dataset
        for key in ("active_object_handle_id", "active_result_handle_id", "active_subset_handle_id"):
            value = str(snapshot.get(key, "") or "").strip()
            if value:
                candidates[key] = value
        return candidates

    def apply_execution_binding_to_constraints(
        self,
        constraints: dict[str, Any],
        execution: QueryExecutionPlan,
    ) -> dict[str, Any]:
        merged = dict(constraints)
        tool_input = dict(getattr(execution, "tool_input", {}) or {})
        pdf_path = str(tool_input.get("path", "") or "").strip()
        if pdf_path and str(getattr(execution.query_understanding, "tool_name", "") or "") == "pdf_analysis":
            merged["active_pdf"] = pdf_path
            merged["active_binding_identity"] = pdf_path.replace("\\", "/").strip().lower()
            merged.setdefault("source_kind", "pdf")
            if str(tool_input.get("mode", "") or "").strip():
                merged["pdf_mode"] = self._normalize_pdf_scope(str(tool_input.get("mode", "") or "").strip())
        binding = getattr(execution, "structured_binding", None)
        if binding is None:
            return merged
        dataset_path = str(getattr(binding, "dataset_path", "") or "").strip()
        if dataset_path:
            merged["active_dataset"] = dataset_path
            merged["active_binding_identity"] = str(
                getattr(binding, "binding_identity", "") or dataset_path.replace("\\", "/").strip().lower()
            )
            merged.setdefault("source_kind", "dataset")
        return merged

    def binding_identity_from_constraints(self, constraints: dict[str, Any]) -> str:
        explicit = str(constraints.get("active_binding_identity", "") or "").strip()
        if explicit:
            return explicit
        active_pdf = str(constraints.get("active_pdf", "") or "").strip()
        if active_pdf:
            return active_pdf.replace("\\", "/").lower()
        active_dataset = str(constraints.get("active_dataset", "") or "").strip()
        if active_dataset:
            return active_dataset.replace("\\", "/").lower()
        return ""

    def extract_active_constraints(self, message: str) -> dict[str, Any]:
        lowered = message.lower()
        constraints: dict[str, Any] = {}
        top_match = None
        for pattern in (r"(?:前|top\s*)(\d+)",):
            top_match = re.search(pattern, message, flags=re.IGNORECASE)
            if top_match:
                break
        if top_match:
            constraints["top_n"] = int(top_match.group(1))
        if "一句话" in message or "一句" in message:
            constraints["response_style"] = "one_sentence"
        elif "简要" in message or "简短" in message:
            constraints["response_style"] = "brief"
        page_match = re.search(r"第\s*(\d+)\s*页", message)
        if page_match:
            constraints["page"] = int(page_match.group(1))
            constraints["pdf_mode"] = "page"
        elif re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*页", message):
            constraints["pdf_mode"] = "page"
        elif re.search(r"page\s*\d+", lowered):
            constraints["pdf_mode"] = "page"
        section_match = re.search(r"(第\s*[零一二三四五六七八九十百千两\d]+\s*(?:部分|章|节))", message)
        if section_match:
            constraints["pdf_mode"] = "section"
            constraints["pdf_section"] = str(section_match.group(1) or "").strip()
        else:
            for marker in ("这一部分", "那一部分", "这一章", "那一章", "这一节", "那一节"):
                if marker in message:
                    constraints["pdf_mode"] = "section"
                    constraints["pdf_section"] = marker
                    break
        if "按仓库" in message:
            constraints["group_by"] = "仓库"
        elif "按地区" in message:
            constraints["group_by"] = "地区"
        if "不要重复" in message:
            constraints["dedupe"] = True
        if "补一句" in message:
            constraints["append_mode"] = "single_sentence_append"
        has_pdf_overview_hint = any(
            marker in message for marker in ("全文总览", "总览", "概览", "核心结论", "行动建议", "完整总结", "详细解读")
        )
        if has_pdf_overview_hint and constraints.get("pdf_mode") not in {"page", "section"}:
            constraints["pdf_mode"] = "document"
        if "pdf" in lowered:
            constraints["source_kind"] = "pdf"
            constraints.setdefault("pdf_mode", "document")
        elif any(ext in lowered for ext in (".xlsx", ".csv", ".xls")):
            constraints["source_kind"] = "dataset"
        return constraints

    def merge_constraints_from_results(
        self,
        constraints: dict[str, Any],
        results: list[dict[str, object]],
    ) -> dict[str, Any]:
        merged = dict(constraints)
        for item in reversed(results):
            context_ref_payload = item.get("context_ref")
            if not isinstance(context_ref_payload, dict):
                continue
            bindings = dict(context_ref_payload.get("bindings") or {})
            binding_identity = str(bindings.get("active_binding_identity", "") or "").strip()
            if bindings.get("active_pdf") and not merged.get("active_pdf"):
                merged["active_pdf"] = str(bindings["active_pdf"])
                merged.setdefault(
                    "active_binding_identity",
                    binding_identity or str(bindings["active_pdf"]).replace("\\", "/").strip().lower(),
                )
            if bindings.get("active_dataset") and not merged.get("active_dataset"):
                merged["active_dataset"] = str(bindings["active_dataset"])
                merged.setdefault(
                    "active_binding_identity",
                    binding_identity or str(bindings["active_dataset"]).replace("\\", "/").strip().lower(),
                )
            if bindings.get("active_location") and not merged.get("active_location"):
                merged["active_location"] = str(bindings["active_location"])
            if bindings.get("source_kind") and not merged.get("source_kind"):
                merged["source_kind"] = str(bindings["source_kind"])
            constraints_payload = item.get("context_ref")
            if isinstance(constraints_payload, dict):
                task_constraints = dict(constraints_payload.get("constraints") or {})
                if task_constraints.get("page") is not None and merged.get("page") is None:
                    merged["page"] = int(task_constraints["page"])
                if task_constraints.get("group_by") and not merged.get("group_by"):
                    merged["group_by"] = str(task_constraints["group_by"])
                if task_constraints.get("pdf_mode") and not merged.get("pdf_mode"):
                    merged["pdf_mode"] = str(task_constraints["pdf_mode"])
                if task_constraints.get("pdf_section") and not merged.get("pdf_section"):
                    merged["pdf_section"] = str(task_constraints["pdf_section"])
                if task_constraints.get("pdf_focus_pages") and not merged.get("pdf_focus_pages"):
                    merged["pdf_focus_pages"] = list(task_constraints["pdf_focus_pages"])
                if task_constraints.get("readable_pages") is not None and merged.get("readable_pages") is None:
                    merged["readable_pages"] = int(task_constraints["readable_pages"])
                if task_constraints.get("usable_pages") is not None and merged.get("usable_pages") is None:
                    merged["usable_pages"] = int(task_constraints["usable_pages"])
                if task_constraints.get("total_pages") is not None and merged.get("total_pages") is None:
                    merged["total_pages"] = int(task_constraints["total_pages"])
        return merged
