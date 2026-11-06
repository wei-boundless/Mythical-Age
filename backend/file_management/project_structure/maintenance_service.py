from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from core.project_layout import ProjectLayout
from memory_system.working_memory_service import WorkingMemoryService

from .change_models import (
    GitChangeSetRecord,
    NetworkMaintenanceProjection,
)
from .semantic_models import (
    NetworkMaintenanceRunRecord,
    SemanticRepairWorkItemRecord,
)
from .repository import ProjectStructureRepository, content_hash, stable_project_structure_id
from .skeleton_refs import file_ref, folder_ref


class ProjectStructureMaintenanceService:
    authority = "file_management.project_structure.maintenance_service"

    def __init__(
        self,
        *,
        repository: ProjectStructureRepository,
        project_root: str | Path,
        working_memory: WorkingMemoryService | None = None,
    ) -> None:
        self.repository = repository
        self.project_root = Path(project_root).resolve()
        self.working_memory = working_memory

    @classmethod
    def from_backend_dir(cls, base_dir: str | Path, *, with_working_memory: bool = False) -> "ProjectStructureMaintenanceService":
        layout = ProjectLayout.from_backend_dir(base_dir)
        return cls(
            repository=ProjectStructureRepository(base_dir),
            project_root=layout.project_root,
            working_memory=WorkingMemoryService(layout.working_memory_dir) if with_working_memory else None,
        )

    def collect_git_change_set(
        self,
        *,
        build_id: str,
        change_mode: str = "working_tree",
        skeleton_generation: int | None = None,
    ) -> GitChangeSetRecord:
        resolved_build_id = str(build_id or "").strip()
        if not resolved_build_id:
            raise ValueError("ProjectStructureMaintenanceService.collect_git_change_set requires build_id")
        generation = int(skeleton_generation or 0) or _latest_generation(self.repository, resolved_build_id)
        status_entries = _git_status(self.project_root)
        changed_files = tuple(sorted(dict.fromkeys(entry.path for entry in status_entries if entry.path)))
        deleted_files = tuple(sorted(entry.path for entry in status_entries if "D" in entry.status and entry.path))
        added_files = tuple(sorted(entry.path for entry in status_entries if ("A" in entry.status or "??" in entry.status) and entry.path))
        renamed_files = tuple({"old_path": entry.old_path, "new_path": entry.path} for entry in status_entries if entry.old_path and entry.path)
        touched_node_ids = self._touched_physical_node_ids(build_id=resolved_build_id, generation=generation, changed_files=changed_files)
        touched_edge_ids = self._touched_edge_ids(build_id=resolved_build_id, generation=generation, node_ids=touched_node_ids)
        semantic_refs = self._semantic_refs_to_mark_stale(build_id=resolved_build_id, node_ids=touched_node_ids)
        head_ref = _git_text(self.project_root, "rev-parse", "--verify", "HEAD")
        payload_hash = content_hash(
            {
                "build_id": resolved_build_id,
                "mode": change_mode,
                "head": head_ref,
                "changed_files": changed_files,
                "renamed_files": renamed_files,
                "deleted_files": deleted_files,
                "added_files": added_files,
                "generation": generation,
            }
        )
        record = GitChangeSetRecord(
            change_set_id=stable_project_structure_id("pngitchange", resolved_build_id, change_mode, payload_hash),
            build_id=resolved_build_id,
            base_ref=head_ref,
            head_ref=head_ref,
            change_mode=change_mode,
            changed_files=changed_files,
            renamed_files=renamed_files,
            deleted_files=deleted_files,
            added_files=added_files,
            diff_stats=_git_diff_stats(self.project_root),
            touched_skeleton_node_ids=touched_node_ids,
            touched_skeleton_edge_ids=touched_edge_ids,
            semantic_refs_to_mark_stale=semantic_refs,
            status="candidate",
        )
        return self.repository.upsert_git_change_set(record)

    def create_repair_work_items(
        self,
        *,
        change_set_id: str,
        skeleton_generation: int | None = None,
        group_by_folder_threshold: int = 40,
    ) -> tuple[SemanticRepairWorkItemRecord, ...]:
        change_set = self.repository.get_git_change_set(change_set_id)
        if change_set is None:
            raise KeyError(f"Unknown git change set: {change_set_id}")
        generation = int(skeleton_generation or 0) or _latest_generation(self.repository, change_set.build_id)
        grouped = _repair_scopes(change_set, threshold=group_by_folder_threshold)
        records: list[SemanticRepairWorkItemRecord] = []
        for scope_key, node_ids in grouped.items():
            priority = 90 if len(node_ids) == 1 else 70
            records.append(
                SemanticRepairWorkItemRecord(
                    work_item_id=stable_project_structure_id("pnrepair", change_set.build_id, change_set.change_set_id, scope_key),
                    build_id=change_set.build_id,
                    change_set_id=change_set.change_set_id,
                    skeleton_generation=generation,
                    repair_kind="refresh_semantic_overlay_for_changed_physical_scope",
                    assigned_scope={"scope_key": scope_key, "minimum_physical_unit": "file_module"},
                    affected_node_ids=tuple(node_ids),
                    affected_edge_ids=change_set.touched_skeleton_edge_ids,
                    previous_semantic_refs=change_set.semantic_refs_to_mark_stale,
                    required_evidence_refs=tuple(f"git-change:{path}" for path in change_set.changed_files),
                    priority=priority,
                    status="queued",
                    metadata={
                        "physical_layer_source": "git_status_plus_skeleton_node_mapping",
                        "semantic_layer_action": "review_existing_overlay_and_update_only_when_meaning_changed",
                    },
                )
            )
        stored = self.repository.upsert_repair_work_items(tuple(records))
        run = NetworkMaintenanceRunRecord(
            maintenance_run_id=stable_project_structure_id("pnmaint", change_set.build_id, change_set.change_set_id),
            build_id=change_set.build_id,
            change_set_id=change_set.change_set_id,
            status="planned",
            affected_node_ids=change_set.touched_skeleton_node_ids,
            affected_edge_ids=change_set.touched_skeleton_edge_ids,
            repair_work_item_ids=tuple(item.work_item_id for item in stored),
        )
        self.repository.upsert_maintenance_run(run)
        return stored

    def build_projection(
        self,
        *,
        change_set_id: str,
        task_run_id: str = "",
        write_shared_memory: bool = False,
    ) -> NetworkMaintenanceProjection:
        change_set = self.repository.get_git_change_set(change_set_id)
        if change_set is None:
            raise KeyError(f"Unknown git change set: {change_set_id}")
        work_items = self.repository.list_repair_work_items(build_id=change_set.build_id, change_set_id=change_set.change_set_id)
        shared_memory = ()
        if write_shared_memory and self.working_memory is not None and task_run_id:
            item = self.working_memory.create_item(
                task_run_id=task_run_id,
                graph_id=change_set.build_id,
                owner_node_id="project_structure_maintenance",
                kind="project_structure_maintenance_summary",
                memory_semantics="working_fact",
                title="Project network maintenance change set",
                summary=f"{len(change_set.changed_files)} files changed; {len(work_items)} semantic repair work items queued.",
                scope="graph_scope",
                visibility="shared_in_graph",
                status="accepted",
                payload={
                    "change_set_id": change_set.change_set_id,
                    "changed_files": list(change_set.changed_files),
                    "repair_work_item_ids": [item.work_item_id for item in work_items],
                },
                metadata={
                    "formal_memory": {
                        "repository_id": "project_structure",
                        "collection_id": "maintenance",
                        "record_kind": "maintenance_change_set",
                        "status": "committed",
                    }
                },
            )
            shared_memory = (item.to_dict(),)
        return NetworkMaintenanceProjection(
            build_id=change_set.build_id,
            change_set=change_set,
            work_items=work_items,
            shared_memory=shared_memory,
        )

    def _touched_physical_node_ids(self, *, build_id: str, generation: int, changed_files: tuple[str, ...]) -> tuple[str, ...]:
        node_ids: list[str] = []
        all_nodes = self.repository.list_skeleton_nodes(build_id=build_id, generation=generation, limit=10000)
        for path in changed_files:
            normalized = path.replace("\\", "/").strip("/")
            direct_refs = (file_ref(normalized), folder_ref(normalized))
            for stable_ref in direct_refs:
                node = self.repository.find_skeleton_node(build_id=build_id, stable_ref=stable_ref, generation=generation)
                if node is not None:
                    node_ids.append(node.node_id)
            if normalized.endswith("/") or any(node.path == normalized and node.node_kind == "folder" for node in all_nodes):
                prefix = normalized.rstrip("/") + "/"
                node_ids.extend(node.node_id for node in all_nodes if node.path == normalized.rstrip("/") or node.path.startswith(prefix))
        return tuple(dict.fromkeys(node_ids))

    def _touched_edge_ids(self, *, build_id: str, generation: int, node_ids: tuple[str, ...]) -> tuple[str, ...]:
        edge_ids: list[str] = []
        for node_id in node_ids:
            edge_ids.extend(
                edge.edge_id
                for edge in self.repository.list_skeleton_edges(build_id=build_id, generation=generation, src_node_id=node_id, limit=500)
            )
            edge_ids.extend(
                edge.edge_id
                for edge in self.repository.list_skeleton_edges(build_id=build_id, generation=generation, dst_node_id=node_id, limit=500)
            )
        return tuple(dict.fromkeys(edge_ids))

    def _semantic_refs_to_mark_stale(self, *, build_id: str, node_ids: tuple[str, ...]) -> tuple[str, ...]:
        refs: list[str] = []
        for node_id in node_ids:
            node = self.repository.get_skeleton_node(node_id)
            if node is None:
                continue
            refs.extend(overlay.overlay_id for overlay in self.repository.list_semantic_overlays(build_id=build_id, stable_ref=node.stable_ref))
        return tuple(dict.fromkeys(refs))


class _GitStatusEntry:
    def __init__(self, *, status: str, path: str, old_path: str = "") -> None:
        self.status = status
        self.path = path
        self.old_path = old_path


def _git_status(project_root: Path) -> tuple[_GitStatusEntry, ...]:
    output = _git_text(project_root, "status", "--porcelain=v1", "--untracked-files=all", "-z")
    if not output:
        return ()
    parts = output.split("\0")
    entries: list[_GitStatusEntry] = []
    index = 0
    while index < len(parts):
        raw = parts[index]
        index += 1
        if not raw:
            continue
        status = raw[:2]
        path = raw[3:].replace("\\", "/").strip()
        old_path = ""
        if status.startswith("R") or status.endswith("R"):
            if index < len(parts):
                old_path = parts[index].replace("\\", "/").strip()
                index += 1
        entries.append(_GitStatusEntry(status=status, path=path, old_path=old_path))
    return tuple(entries)


def _git_diff_stats(project_root: Path) -> dict[str, Any]:
    output = _git_text(project_root, "diff", "--numstat")
    files: list[dict[str, Any]] = []
    total_added = 0
    total_deleted = 0
    for line in output.splitlines():
        added, deleted, path = (line.split("\t", 2) + ["", "", ""])[:3]
        added_count = int(added) if added.isdigit() else 0
        deleted_count = int(deleted) if deleted.isdigit() else 0
        total_added += added_count
        total_deleted += deleted_count
        files.append({"path": path.replace("\\", "/"), "added": added_count, "deleted": deleted_count})
    return {"files": files, "total_added": total_added, "total_deleted": total_deleted}


def _git_text(project_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ("git", *args),
            cwd=str(project_root),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=12,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _latest_generation(repository: ProjectStructureRepository, build_id: str) -> int:
    generations = repository.list_skeleton_generations(build_id=build_id, limit=1)
    return int(generations[0].generation or 0) if generations else 0


def _repair_scopes(change_set: GitChangeSetRecord, *, threshold: int) -> dict[str, tuple[str, ...]]:
    nodes = tuple(change_set.touched_skeleton_node_ids)
    if len(nodes) <= max(1, int(threshold or 40)):
        return {f"node:{node_id}": (node_id,) for node_id in nodes}
    return {"bulk:changed_physical_scope": nodes}
