from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PrimaryExecutionAdapter:
    """Builds a read-only preview of primary execution objects.

    Phase 6H deliberately does not create runnable QueryExecutionPlan objects.
    It only records how primary would map low-risk entries onto existing legacy
    executions, so runtime can compare safely before any real cutover.
    """

    adapter_version: str = "phase6h-preview-v1"

    def build_preview(
        self,
        *,
        entries: list[dict[str, Any]],
        entry_selection: dict[str, Any],
        legacy_by_id: dict[str, Any],
    ) -> dict[str, Any]:
        state = str(entry_selection.get("state") or "missing")
        enabled = bool(entry_selection.get("enabled"))
        if not enabled:
            return self._summary(state="disabled", reason="primary_entry_selection_disabled")
        if state != "ready":
            return self._summary(
                state=state or "blocked",
                reason=f"entry_selection_not_ready:{state or 'missing'}",
                blocked_entries=list(entry_selection.get("blocked_entries") or []),
            )

        preview_executions: list[dict[str, Any]] = []
        mismatches: list[dict[str, str]] = []
        for entry in entries:
            execution_id = str(entry.get("execution_id") or "")
            legacy = legacy_by_id.get(execution_id)
            if legacy is None:
                mismatches.append(
                    {
                        "execution_id": execution_id,
                        "field": "legacy_execution",
                        "primary": "selected",
                        "legacy": "missing",
                    }
                )
                continue
            preview = self._preview_execution(entry=entry, legacy=legacy)
            preview_executions.append(preview)
            mismatches.extend(self._preview_mismatches(preview))

        if mismatches:
            return self._summary(
                state="mismatch",
                reason="primary_preview_legacy_mismatch",
                preview_executions=preview_executions,
                mismatches=mismatches,
            )
        return self._summary(
            state="ready",
            reason="primary_execution_preview_ready",
            preview_executions=preview_executions,
        )

    def _summary(
        self,
        *,
        state: str,
        reason: str,
        preview_executions: list[dict[str, Any]] | None = None,
        mismatches: list[dict[str, str]] | None = None,
        blocked_entries: list[Any] | None = None,
    ) -> dict[str, Any]:
        previews = list(preview_executions or [])
        mismatch_items = list(mismatches or [])
        return {
            "adapter_version": self.adapter_version,
            "state": state,
            "reason": reason,
            "execution_count": len(previews),
            "mismatch_count": len(mismatch_items),
            "preview_executions": previews,
            "mismatches": mismatch_items,
            "blocked_entries": list(blocked_entries or []),
            "executable_contract": self._executable_contract(
                state=state,
                preview_executions=previews,
                mismatches=mismatch_items,
                blocked_entries=list(blocked_entries or []),
            ),
            "output_source": "legacy_final_output",
        }

    def _preview_execution(self, *, entry: dict[str, Any], legacy: Any) -> dict[str, Any]:
        understanding = getattr(legacy, "query_understanding", None)
        worker_plan = getattr(legacy, "worker_plan", None)
        active_skill = getattr(legacy, "active_skill", None)
        return {
            "execution_id": str(entry.get("execution_id") or ""),
            "entry_kind": str(entry.get("entry_kind") or ""),
            "route": str(entry.get("route") or ""),
            "source": str(entry.get("source") or ""),
            "tool": str(entry.get("tool") or ""),
            "worker_route": str(entry.get("worker_route") or ""),
            "skill": str(entry.get("skill") or ""),
            "agent_id": str(entry.get("agent_id") or ""),
            "legacy_execution_kind": str(getattr(legacy, "execution_kind", "") or ""),
            "legacy_route": str(getattr(understanding, "route", "") or ""),
            "legacy_tool": str(getattr(understanding, "tool_name", "") or ""),
            "legacy_worker_route": str(getattr(worker_plan, "worker_route", "") or ""),
            "legacy_skill": str(getattr(active_skill, "name", "") or getattr(understanding, "skill_name", "") or ""),
            "mapping_status": "matched",
            "output_source": "legacy_final_output",
        }

    def _preview_mismatches(self, preview: dict[str, Any]) -> list[dict[str, str]]:
        checks = {
            "route": (str(preview.get("route") or ""), str(preview.get("legacy_route") or "")),
            "tool": (str(preview.get("tool") or ""), str(preview.get("legacy_tool") or "")),
            "worker_route": (
                str(preview.get("worker_route") or ""),
                str(preview.get("legacy_worker_route") or ""),
            ),
            "skill": (str(preview.get("skill") or ""), str(preview.get("legacy_skill") or "")),
        }
        mismatches: list[dict[str, str]] = []
        for field_name, (primary_value, legacy_value) in checks.items():
            if not primary_value or not legacy_value or primary_value == legacy_value:
                continue
            mismatches.append(
                {
                    "execution_id": str(preview.get("execution_id") or ""),
                    "field": field_name,
                    "primary": primary_value,
                    "legacy": legacy_value,
                }
            )
        return mismatches

    def _executable_contract(
        self,
        *,
        state: str,
        preview_executions: list[dict[str, Any]],
        mismatches: list[dict[str, str]],
        blocked_entries: list[Any],
    ) -> dict[str, Any]:
        if state != "ready":
            return {
                "phase": "7C",
                "state": state if state in {"disabled", "blocked", "mismatch"} else "blocked",
                "reason": f"primary_preview_not_ready:{state or 'missing'}",
                "cutover_state": "preview_only",
                "runnable": False,
                "required_gates": self._required_gates(),
                "execution_specs": [],
                "blocked_entries": blocked_entries,
                "mismatch_count": len(mismatches),
                "output_source": "legacy_final_output",
            }
        return {
            "phase": "7C",
            "state": "preview_ready",
            "reason": "execution_directive_contract_ready",
            "cutover_state": "preview_only",
            "runnable": False,
            "required_gates": self._required_gates(),
            "execution_specs": [self._execution_spec(item) for item in preview_executions],
            "blocked_entries": [],
            "mismatch_count": 0,
            "output_source": "legacy_final_output",
        }

    def _execution_spec(self, preview: dict[str, Any]) -> dict[str, Any]:
        entry_kind = str(preview.get("entry_kind") or "")
        action = "respond"
        if entry_kind == "worker":
            action = "delegate_agent"
        elif entry_kind == "direct_tool":
            action = "call_tool"
        return {
            "execution_id": str(preview.get("execution_id") or ""),
            "action": action,
            "entry_kind": entry_kind,
            "source": str(preview.get("source") or ""),
            "tool": str(preview.get("tool") or ""),
            "worker_route": str(preview.get("worker_route") or ""),
            "agent_id": str(preview.get("agent_id") or ""),
            "skill": str(preview.get("skill") or ""),
            "runtime_bridge_required": True,
            "validator_required": True,
            "search_policy_required": True,
            "tool_contract_required": True,
            "agent_binding_required": True,
            "output_source": "legacy_final_output",
        }

    def _required_gates(self) -> list[str]:
        return [
            "validation",
            "runtime_tool_bridge",
            "search_policy",
            "tool_contract",
            "agent_binding",
            "output_boundary",
        ]
