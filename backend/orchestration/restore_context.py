from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


RESTORE_CONTEXT_KEYS = (
    "active_pdf",
    "active_dataset",
    "active_object_handle_id",
    "active_result_handle_id",
    "active_subset_handle_id",
)


@dataclass(slots=True)
class RestoreAuthorityContextGateResult:
    context: dict[str, Any]
    diagnostics: dict[str, Any] = field(default_factory=dict)


class RestoreAuthorityContextGate:
    """First-cut seam between session restore candidates and planner authority_context."""

    def filter_for_planner(
        self,
        *,
        restore_candidates: dict[str, Any] | None,
        restore_shadow_consumer_enabled: bool,
        restore_shadow_consumer_mode: str,
    ) -> RestoreAuthorityContextGateResult:
        normalized = self._normalize_context(restore_candidates)
        mode = self._normalize_mode(restore_shadow_consumer_mode)
        first_cut_active = bool(restore_shadow_consumer_enabled and mode == "observe_only")
        if not first_cut_active:
            return RestoreAuthorityContextGateResult(
                context=dict(normalized),
                diagnostics=self._diagnostics(
                    state="legacy_passthrough",
                    mode=mode,
                    candidate_context=normalized,
                    filtered_context=normalized,
                    reason="restore_authority_context_first_cut_disabled",
                ),
            )

        filtered = {
            key: value
            for key, value in normalized.items()
            if key in RESTORE_CONTEXT_KEYS and str(value or "").strip()
        }
        return RestoreAuthorityContextGateResult(
            context=filtered,
            diagnostics=self._diagnostics(
                state="orchestration_filtered",
                mode=mode,
                candidate_context=normalized,
                filtered_context=filtered,
                reason="restore_authority_context_first_cut_active",
            ),
        )

    def _normalize_context(self, context: dict[str, Any] | None) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key in RESTORE_CONTEXT_KEYS:
            value = str((context or {}).get(key, "") or "").strip()
            if value:
                normalized[key] = value
        return normalized

    def _normalize_mode(self, mode: str) -> str:
        normalized = str(mode or "disabled").strip().lower()
        return normalized if normalized in {"disabled", "observe_only"} else "disabled"

    def _diagnostics(
        self,
        *,
        state: str,
        mode: str,
        candidate_context: dict[str, Any],
        filtered_context: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        return {
            "phase": "8I",
            "state": state,
            "mode": mode,
            "reason": reason,
            "candidate_keys": sorted(candidate_context),
            "legacy_keys": sorted(candidate_context),
            "filtered_keys": sorted(filtered_context),
            "candidate_context_present": bool(candidate_context),
            "legacy_context_present": bool(candidate_context),
            "planner_context_present": bool(filtered_context),
            "state_write_allowed": False,
            "takeover_allowed": False,
            "delete_allowed": False,
            "replacement_seam": "orchestration.restore_context.RestoreAuthorityContextGate",
        }
