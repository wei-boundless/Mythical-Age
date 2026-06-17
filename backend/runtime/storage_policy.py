from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


SECONDS_PER_DAY = 24 * 60 * 60
MB = 1024 * 1024
GB = 1024 * MB


@dataclass(frozen=True, slots=True)
class RuntimeRetentionRule:
    rule_id: str
    storage_class: str
    tier: str
    ttl_seconds: int
    max_bytes: int
    action: str
    protected_while_active: bool = False
    authority: str = "runtime.storage_policy"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ttl_days"] = round(self.ttl_seconds / SECONDS_PER_DAY, 4) if self.ttl_seconds else 0
        payload["max_mb"] = round(self.max_bytes / MB, 2) if self.max_bytes else 0
        return payload


@dataclass(frozen=True, slots=True)
class RuntimeStoragePolicy:
    """Single source of truth for runtime/cache retention budgets.

    This policy class owns retention times and size budgets only. Writers still
    write facts, artifact governance still classifies project assets, and
    maintenance executors perform the actual deletion/compaction work.
    """

    active_detail_window_seconds: int = SECONDS_PER_DAY
    terminal_hot_seconds: int = 7 * SECONDS_PER_DAY
    terminal_summary_seconds: int = 180 * SECONDS_PER_DAY
    event_summary_seconds: int = 30 * SECONDS_PER_DAY
    cold_archive_seconds: int = 90 * SECONDS_PER_DAY
    manual_hold_review_seconds: int = 365 * SECONDS_PER_DAY
    sandbox_cache_ttl_seconds: int = SECONDS_PER_DAY
    diagnostic_ttl_seconds: int = 7 * SECONDS_PER_DAY
    temporary_output_ttl_seconds: int = 3 * SECONDS_PER_DAY
    prompt_map_hot_seconds: int = SECONDS_PER_DAY
    prompt_usage_hot_seconds: int = 7 * SECONDS_PER_DAY
    event_payload_hot_seconds: int = SECONDS_PER_DAY
    event_payload_terminal_hot_seconds: int = 3 * SECONDS_PER_DAY
    prompt_map_keep_latest_per_scope: int = 20
    prompt_segment_keep_latest_per_session: int = 200
    prompt_usage_keep_latest_per_task: int = 2000
    event_payload_keep_latest_per_run: int = 50
    playwright_keep_latest: int = 20
    l0_single_run_budget_bytes: int = 512 * MB
    l0_project_budget_bytes: int = 2 * GB
    l1_single_run_budget_bytes: int = 32 * MB
    l1_project_budget_bytes: int = GB
    l2_single_run_budget_bytes: int = GB
    l2_project_budget_bytes: int = 10 * GB
    l3_single_cache_budget_bytes: int = 256 * MB
    l3_project_budget_bytes: int = 2 * GB
    authority: str = "runtime.storage_policy"

    def retention_rules(self) -> tuple[RuntimeRetentionRule, ...]:
        return (
            RuntimeRetentionRule(
                "runtime_active_detail",
                "runtime_fact",
                "L0_hot",
                self.active_detail_window_seconds,
                self.l0_single_run_budget_bytes,
                "keep_hot_window",
                protected_while_active=True,
            ),
            RuntimeRetentionRule(
                "terminal_hot_runtime_fact",
                "runtime_fact",
                "L0_hot",
                self.terminal_hot_seconds,
                self.l0_single_run_budget_bytes,
                "summarize_then_cold_archive",
            ),
            RuntimeRetentionRule(
                "terminal_run_summary",
                "runtime_summary",
                "L1_warm",
                self.terminal_summary_seconds,
                self.l1_single_run_budget_bytes,
                "keep_summary",
            ),
            RuntimeRetentionRule(
                "event_summary",
                "runtime_event_summary",
                "L1_warm",
                self.event_summary_seconds,
                self.l1_single_run_budget_bytes,
                "keep_summary",
            ),
            RuntimeRetentionRule(
                "cold_runtime_archive",
                "runtime_archive",
                "L2_cold",
                self.cold_archive_seconds,
                self.l2_single_run_budget_bytes,
                "delete_expired_archive",
            ),
            RuntimeRetentionRule(
                "manual_hold_archive_review",
                "runtime_archive",
                "L2_cold",
                self.manual_hold_review_seconds,
                self.l2_single_run_budget_bytes,
                "review_manual_hold",
            ),
            RuntimeRetentionRule(
                "sandbox_cache",
                "rebuildable_cache",
                "L3_rebuildable",
                self.sandbox_cache_ttl_seconds,
                self.l3_single_cache_budget_bytes,
                "delete_expired_cache",
                protected_while_active=True,
            ),
            RuntimeRetentionRule(
                "diagnostic_trace",
                "diagnostic_artifact",
                "L3_rebuildable",
                self.diagnostic_ttl_seconds,
                self.l3_project_budget_bytes,
                "delete_expired_diagnostic",
            ),
            RuntimeRetentionRule(
                "temporary_output",
                "diagnostic_artifact",
                "L3_rebuildable",
                self.temporary_output_ttl_seconds,
                self.l3_project_budget_bytes,
                "delete_expired_temporary_output",
            ),
            RuntimeRetentionRule(
                "prompt_map_hot_detail",
                "prompt_accounting_map",
                "L0_hot",
                self.prompt_map_hot_seconds,
                self.l1_single_run_budget_bytes,
                "time_bucket_then_compact_to_summary",
                protected_while_active=True,
            ),
            RuntimeRetentionRule(
                "prompt_usage_hot_detail",
                "prompt_accounting_usage",
                "L0_hot",
                self.prompt_usage_hot_seconds,
                self.l1_single_run_budget_bytes,
                "time_bucket_then_compact_to_retained_token_stats",
                protected_while_active=True,
            ),
            RuntimeRetentionRule(
                "event_payload_hot_detail",
                "runtime_event_payload",
                "L0_hot",
                self.event_payload_hot_seconds,
                self.l1_single_run_budget_bytes,
                "time_bucket_then_compress_or_archive",
                protected_while_active=True,
            ),
            RuntimeRetentionRule(
                "frontend_next_cache",
                "rebuildable_cache",
                "L3_rebuildable",
                0,
                self.l3_project_budget_bytes,
                "delete_on_maintenance_or_restart",
            ),
        )

    def rule(self, rule_id: str) -> RuntimeRetentionRule:
        target = str(rule_id or "").strip()
        for rule in self.retention_rules():
            if rule.rule_id == target:
                return rule
        raise KeyError(f"unknown runtime retention rule: {target}")

    def protected_durability_classes(self) -> set[str]:
        return {"user_asset", "project_artifact"}

    def auto_delete_durability_classes(self) -> set[str]:
        return {"diagnostic_artifact", "rebuildable_cache"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "protected_durability_classes": sorted(self.protected_durability_classes()),
            "auto_delete_durability_classes": sorted(self.auto_delete_durability_classes()),
            "rules": {rule.rule_id: rule.to_dict() for rule in self.retention_rules()},
            "budgets": {
                "L0_hot": {
                    "single_run_mb": round(self.l0_single_run_budget_bytes / MB, 2),
                    "project_mb": round(self.l0_project_budget_bytes / MB, 2),
                },
                "L1_warm": {
                    "single_run_mb": round(self.l1_single_run_budget_bytes / MB, 2),
                    "project_mb": round(self.l1_project_budget_bytes / MB, 2),
                },
                "L2_cold": {
                    "single_run_mb": round(self.l2_single_run_budget_bytes / MB, 2),
                    "project_mb": round(self.l2_project_budget_bytes / MB, 2),
                },
                "L3_rebuildable": {
                    "single_cache_mb": round(self.l3_single_cache_budget_bytes / MB, 2),
                    "project_mb": round(self.l3_project_budget_bytes / MB, 2),
                },
            },
            "time_bucket_controls": {
                "prompt_accounting_hot_root": "storage/runtime_state/prompt_accounting/hot/by_time/YYYYMMDD/HH",
                "event_payload_hot_root": "storage/runtime_state/event_payloads/hot/by_time/YYYYMMDD/HH",
                "prompt_map_hot_seconds": self.prompt_map_hot_seconds,
                "prompt_usage_hot_seconds": self.prompt_usage_hot_seconds,
                "event_payload_hot_seconds": self.event_payload_hot_seconds,
                "event_payload_terminal_hot_seconds": self.event_payload_terminal_hot_seconds,
                "prompt_map_keep_latest_per_scope": self.prompt_map_keep_latest_per_scope,
                "prompt_segment_keep_latest_per_session": self.prompt_segment_keep_latest_per_session,
                "prompt_usage_keep_latest_per_task": self.prompt_usage_keep_latest_per_task,
                "event_payload_keep_latest_per_run": self.event_payload_keep_latest_per_run,
            },
        }


DEFAULT_RUNTIME_STORAGE_POLICY = RuntimeStoragePolicy()
