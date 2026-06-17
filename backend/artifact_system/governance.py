from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout


@dataclass(frozen=True, slots=True)
class ArtifactPortPolicy:
    port_id: str
    root: str
    owner_system: str
    artifact_class: str
    storage_layer: str = "durable_fact"
    durability_class: str = "runtime_fact"
    retention_tier: str = "L0_hot"
    source_of_truth: bool = False
    recoverability: str = "rebuildable"
    retention_policy: str = "managed"
    maintenance_authority: str = "artifact_system.governance"

    def to_dict(self) -> dict[str, Any]:
        return {
            "port_id": self.port_id,
            "root": self.root,
            "owner_system": self.owner_system,
            "artifact_class": self.artifact_class,
            "storage_layer": self.storage_layer,
            "durability_class": self.durability_class,
            "retention_tier": self.retention_tier,
            "source_of_truth": self.source_of_truth,
            "recoverability": self.recoverability,
            "retention_policy": self.retention_policy,
            "maintenance_authority": self.maintenance_authority,
        }


class ArtifactGovernanceRegistry:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()

    def policies(self) -> tuple[ArtifactPortPolicy, ...]:
        return (
            ArtifactPortPolicy("runtime.events", "storage/runtime_state/events", "RuntimeSystem", "runtime_fact", "durable_fact", "runtime_fact", "L0_hot", True, "recovery_critical", "archive_not_delete"),
            ArtifactPortPolicy("runtime.event_index", "storage/runtime_state/event_index", "RuntimeSystem", "runtime_projection", "projection", "rebuildable_cache", "L3_rebuildable", False, "rebuildable", "rebuild_or_delete"),
            ArtifactPortPolicy("runtime.checkpoints", "storage/runtime_state/graph_checkpoints.sqlite*", "RuntimeSystem", "runtime_fact", "durable_fact", "runtime_fact", "L0_hot", True, "recovery_critical", "compact_only"),
            ArtifactPortPolicy("runtime.objects", "storage/runtime_state/runtime_objects", "RuntimeSystem", "runtime_fact", "durable_fact", "runtime_fact", "L2_cold", True, "reference_reachable", "quarantine_then_delete"),
            ArtifactPortPolicy("runtime.state_index", "storage/runtime_state/state_index", "RuntimeSystem", "runtime_fact", "durable_fact", "runtime_fact", "L1_warm", True, "recovery_index", "prune_with_task_records"),
            ArtifactPortPolicy("runtime.prompt_accounting", "storage/runtime_state/prompt_accounting", "RuntimeSystem", "runtime_fact", "durable_fact", "runtime_fact", "L1_warm", True, "audit_ledger", "archive_not_delete"),
            ArtifactPortPolicy("runtime.executions", "storage/runtime_state/executions", "RuntimeSystem", "diagnostic_trace", "diagnostic", "diagnostic_artifact", "L3_rebuildable", False, "diagnostic", "ttl"),
            ArtifactPortPolicy("runtime.sandbox_cache", "storage/runtime_cache/sandboxes", "RuntimeSystem", "sandbox_cache", "dynamic_cache", "rebuildable_cache", "L3_rebuildable", False, "rebuildable", "ttl_and_active_task_retention"),
            ArtifactPortPolicy("tasks.records", "storage/tasks", "TaskSystem", "task_record", "durable_fact", "runtime_fact", "L1_warm", True, "task_record_managed_by_health", "partition_snapshots"),
            ArtifactPortPolicy("graph_task_instances.project_artifacts", "storage/graph_task_instances", "TaskSystem", "canonical_artifact", "durable_fact", "project_artifact", "durable_protected", True, "artifact_indexed", "retain"),
            ArtifactPortPolicy("task_environment.artifacts", "storage/task_environments", "ArtifactSystem", "canonical_artifact", "durable_fact", "project_artifact", "durable_protected", True, "artifact_indexed", "hash_and_lifecycle"),
            ArtifactPortPolicy("artifact.repository", "storage/artifact_repository", "ArtifactSystem", "artifact_index", "durable_fact", "runtime_fact", "L1_warm", True, "artifact_index", "retain"),
            ArtifactPortPolicy("knowledge.assets", "../langchain-agent-data/knowledge", "KnowledgeSystem", "knowledge_asset", "durable_fact", "user_asset", "durable_protected", True, "durable_asset", "external_root"),
            ArtifactPortPolicy("diagnostics.local_traces", "output/local_traces", "DiagnosticOutput", "diagnostic_trace", "diagnostic", "diagnostic_artifact", "L3_rebuildable", False, "diagnostic", "ttl_keep_failures"),
            ArtifactPortPolicy("diagnostics.test_runs", "output/test_runs", "DiagnosticOutput", "diagnostic_trace", "diagnostic", "diagnostic_artifact", "L3_rebuildable", False, "diagnostic", "ttl_keep_failures"),
            ArtifactPortPolicy("diagnostics.playwright", "output/playwright", "DiagnosticOutput", "diagnostic_trace", "diagnostic", "diagnostic_artifact", "L3_rebuildable", False, "diagnostic", "keep_last_n"),
            ArtifactPortPolicy("diagnostics.runtime_logs", "output/runtime", "DiagnosticOutput", "diagnostic_trace", "diagnostic", "diagnostic_artifact", "L3_rebuildable", False, "diagnostic", "rotate"),
            ArtifactPortPolicy("diagnostics.novel_artifacts", "output/novel_artifacts", "ArtifactSystem", "canonical_artifact", "diagnostic", "diagnostic_artifact", "L3_rebuildable", False, "legacy_artifact", "legacy_import_or_archive"),
            ArtifactPortPolicy("frontend.next", "frontend/.next", "FrontendBuild", "build_cache", "dynamic_cache", "rebuildable_cache", "L3_rebuildable", False, "rebuildable", "delete_on_restart"),
        )


class ArtifactInventoryService:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.registry = ArtifactGovernanceRegistry(self.project_root)

    @classmethod
    def from_backend_dir(cls, backend_dir: str | Path) -> "ArtifactInventoryService":
        layout = ProjectLayout.from_backend_dir(backend_dir)
        return cls(layout.project_root)

    def build_inventory(self) -> dict[str, Any]:
        records = [self._record(policy) for policy in self.registry.policies()]
        summary: dict[str, Any] = {
            "port_count": len(records),
            "file_count": sum(int(item.get("file_count") or 0) for item in records),
            "size_bytes": sum(int(item.get("size_bytes") or 0) for item in records),
            "protected_size_bytes": sum(int(item.get("size_bytes") or 0) for item in records if item.get("protected")),
            "rebuildable_size_bytes": sum(int(item.get("size_bytes") or 0) for item in records if item.get("recoverability") == "rebuildable"),
        }
        summary["size_mb"] = round(summary["size_bytes"] / 1024 / 1024, 2)
        summary["protected_size_mb"] = round(summary["protected_size_bytes"] / 1024 / 1024, 2)
        summary["rebuildable_size_mb"] = round(summary["rebuildable_size_bytes"] / 1024 / 1024, 2)
        return {
            "authority": "artifact_system.inventory",
            "mode": "read_only",
            "summary": summary,
            "ports": records,
            "updated_at": time.time(),
        }

    def _record(self, policy: ArtifactPortPolicy) -> dict[str, Any]:
        paths = self._resolve_paths(policy.root)
        file_count = 0
        size_bytes = 0
        latest_updated_at = 0.0
        existing_paths: list[str] = []
        for path in paths:
            if not path.exists():
                continue
            existing_paths.append(self._display_path(path))
            files = [path] if path.is_file() else [item for item in path.rglob("*") if item.is_file()]
            for file_path in files:
                try:
                    stat = file_path.stat()
                except OSError:
                    continue
                file_count += 1
                size_bytes += int(stat.st_size)
                latest_updated_at = max(latest_updated_at, float(stat.st_mtime))
        protected = policy.source_of_truth or policy.recoverability not in {"rebuildable", "diagnostic"}
        return {
            **policy.to_dict(),
            "paths": existing_paths,
            "exists": bool(existing_paths),
            "file_count": file_count,
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / 1024 / 1024, 2),
            "latest_updated_at": latest_updated_at,
            "protected": protected,
            "protection_reasons": _protection_reasons(policy, protected=protected),
        }

    def _resolve_paths(self, root_pattern: str) -> list[Path]:
        raw = str(root_pattern or "").strip().replace("\\", "/")
        if not raw:
            return []
        if "*" in raw:
            return [Path(item).resolve() for item in self.project_root.glob(raw)]
        return [(self.project_root / raw).resolve()]

    def _display_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.project_root).as_posix()
        except ValueError:
            return path.resolve().as_posix()


def _protection_reasons(policy: ArtifactPortPolicy, *, protected: bool) -> list[str]:
    reasons: list[str] = []
    if policy.source_of_truth:
        reasons.append("source_of_truth")
    if policy.recoverability in {"recovery_critical", "audit_ledger", "recovery_index", "reference_reachable"}:
        reasons.append(policy.recoverability)
    if policy.artifact_class in {"task_record", "knowledge_asset"}:
        reasons.append(policy.artifact_class)
    if policy.durability_class in {"user_asset", "project_artifact"}:
        reasons.append(policy.durability_class)
    if not protected:
        reasons.append("rebuildable_or_diagnostic")
    return reasons
