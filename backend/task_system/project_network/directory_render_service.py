from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from file_management.project_structure.repository import ProjectStructureRepository
from file_management.project_structure.skeleton_models import SkeletonNodeRecord
from file_management.project_structure.skeleton_refs import folder_ref, normalize_rel_path

from .directory_render_models import (
    DirectoryChildReturnEnvelope,
    DirectoryFrameMaterializationPackage,
    DirectoryManifestProduct,
    DirectoryRenderBudget,
    DirectoryRenderFrame,
    DirectoryRenderProjection,
)
from .repository import ProjectNetworkRepository, content_hash, stable_project_network_id


class DirectoryRenderService:
    """Builds deterministic directory-render frames from the physical skeleton.

    The service owns only graph-task orchestration state. Physical tree facts stay
    in file_management.project_structure, and semantic interpretation stays with
    the agent nodes that consume these frames.
    """

    authority = "task_system.project_network.directory_render_service"

    def __init__(
        self,
        *,
        project_structure_repository: ProjectStructureRepository,
        project_network_repository: ProjectNetworkRepository,
    ) -> None:
        self.project_structure_repository = project_structure_repository
        self.project_network_repository = project_network_repository

    @classmethod
    def from_backend_dir(cls, base_dir: str | Path) -> "DirectoryRenderService":
        return cls(
            project_structure_repository=ProjectStructureRepository(base_dir),
            project_network_repository=ProjectNetworkRepository(base_dir),
        )

    def create_root_frame(
        self,
        *,
        build_id: str,
        skeleton_build_id: str,
        skeleton_generation: int,
        folder_stable_ref: str = "",
        folder_node_id: str = "",
        folder_path: str = "",
        budget: DirectoryRenderBudget | dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DirectoryRenderFrame:
        node = self.resolve_folder_node(
            skeleton_build_id=skeleton_build_id,
            skeleton_generation=skeleton_generation,
            folder_stable_ref=folder_stable_ref,
            folder_node_id=folder_node_id,
            folder_path=folder_path,
        )
        resolved_budget = budget if isinstance(budget, DirectoryRenderBudget) else DirectoryRenderBudget.from_dict(budget)
        frame_id = stable_project_network_id("pndirframe", build_id, skeleton_build_id, skeleton_generation, node.stable_ref)
        frame = DirectoryRenderFrame(
            frame_id=frame_id,
            build_id=build_id,
            root_frame_id=frame_id,
            parent_frame_id="",
            depth=0,
            skeleton_build_id=skeleton_build_id,
            skeleton_generation=skeleton_generation,
            folder_node_id=node.node_id,
            folder_stable_ref=node.stable_ref,
            folder_path=node.path,
            budget=resolved_budget,
            metadata={
                **dict(metadata or {}),
                "authority_boundary": "physical_tree_from_project_structure_repository",
                "algorithm_kind": "tree_reduce",
            },
        )
        return self.project_network_repository.upsert_directory_frame(frame)

    def resolve_folder_node(
        self,
        *,
        skeleton_build_id: str,
        skeleton_generation: int,
        folder_stable_ref: str = "",
        folder_node_id: str = "",
        folder_path: str = "",
    ) -> SkeletonNodeRecord:
        if folder_node_id:
            node = self.project_structure_repository.get_skeleton_node(folder_node_id)
            if node is not None and node.build_id == skeleton_build_id and int(node.generation) == int(skeleton_generation):
                if node.node_kind != "folder":
                    raise ValueError(f"skeleton node is not a folder: {folder_node_id}")
                return node
        stable_ref = str(folder_stable_ref or "").strip()
        if not stable_ref and folder_path:
            stable_ref = folder_ref(normalize_rel_path(folder_path))
        if stable_ref:
            node = self.project_structure_repository.find_skeleton_node(
                build_id=skeleton_build_id,
                generation=skeleton_generation,
                stable_ref=stable_ref,
            )
            if node is not None:
                if node.node_kind != "folder":
                    raise ValueError(f"skeleton stable_ref is not a folder: {stable_ref}")
                return node
        if folder_path:
            rel = normalize_rel_path(folder_path)
            candidates = self.project_structure_repository.list_skeleton_nodes(
                build_id=skeleton_build_id,
                generation=skeleton_generation,
                node_kind="folder",
                path=rel,
                limit=2,
            )
            if candidates:
                return candidates[0]
        raise KeyError(f"folder skeleton node not found: {folder_node_id or folder_stable_ref or folder_path}")

    def materialize_manifest(self, frame: DirectoryRenderFrame | str) -> DirectoryManifestProduct:
        target = self._frame(frame)
        folder_node = self.project_structure_repository.get_skeleton_node(target.folder_node_id)
        if folder_node is None:
            blocked = self.project_network_repository.upsert_directory_frame(replace(target, status="blocked_missing_skeleton"))
            raise KeyError(f"folder skeleton node not found for frame {blocked.frame_id}: {target.folder_node_id}")
        child_folders = self._direct_child_nodes(frame=target, edge_kind="contains_folder")
        direct_files = self._direct_child_nodes(frame=target, edge_kind="contains_file")
        child_folders, skipped_folder_refs = _filter_child_folders(child_folders, budget=target.budget)
        direct_files, skipped_file_refs = _filter_direct_files(direct_files, budget=target.budget)
        manifest_id = stable_project_network_id("pndirmft", target.build_id, target.frame_id, target.folder_stable_ref, target.skeleton_generation)
        manifest_seed = {
            "folder": target.folder_stable_ref,
            "child_folders": [item.stable_ref for item in child_folders],
            "direct_files": [item.stable_ref for item in direct_files],
            "skipped": [*skipped_folder_refs, *skipped_file_refs],
        }
        manifest = DirectoryManifestProduct(
            manifest_id=manifest_id,
            build_id=target.build_id,
            frame_id=target.frame_id,
            skeleton_build_id=target.skeleton_build_id,
            skeleton_generation=target.skeleton_generation,
            folder_node_id=target.folder_node_id,
            folder_stable_ref=target.folder_stable_ref,
            folder_path=target.folder_path,
            child_folder_node_ids=tuple(item.node_id for item in child_folders),
            child_folder_refs=tuple(item.stable_ref for item in child_folders),
            direct_file_node_ids=tuple(item.node_id for item in direct_files),
            direct_file_refs=tuple(item.stable_ref for item in direct_files),
            skipped_refs=tuple([*skipped_folder_refs, *skipped_file_refs]),
            child_folder_nodes=tuple(_node_card(item) for item in child_folders),
            direct_file_nodes=tuple(_node_card(item) for item in direct_files),
            content_hash=content_hash(manifest_seed),
            metadata={
                "tree_algorithm": "direct_children_manifest",
                "source_authority": "file_management.project_structure.skeleton",
                "direct_child_folder_count": len(child_folders),
                "direct_file_count": len(direct_files),
            },
        )
        stored_manifest = self.project_network_repository.upsert_directory_manifest(manifest)
        next_frame = replace(
            target,
            manifest_ref=stored_manifest.manifest_id,
            direct_file_refs=stored_manifest.direct_file_refs,
            status="manifest_ready",
        )
        self.project_network_repository.upsert_directory_frame(next_frame)
        return stored_manifest

    def create_child_frames(self, frame: DirectoryRenderFrame | str, manifest: DirectoryManifestProduct | None = None) -> tuple[DirectoryRenderFrame, ...]:
        target = self._frame(frame)
        resolved_manifest = manifest or self.project_network_repository.get_directory_manifest(target.manifest_ref)
        if resolved_manifest is None:
            resolved_manifest = self.materialize_manifest(target)
        if target.depth >= target.budget.max_depth:
            return ()
        child_frames: list[DirectoryRenderFrame] = []
        for child in resolved_manifest.child_folder_nodes[: target.budget.max_child_folders_per_frame]:
            child_node_id = str(child.get("node_id") or "")
            child_stable_ref = str(child.get("stable_ref") or "")
            if not child_node_id or not child_stable_ref:
                continue
            frame_id = stable_project_network_id("pndirframe", target.build_id, target.root_frame_id or target.frame_id, child_stable_ref)
            child_frame = DirectoryRenderFrame(
                frame_id=frame_id,
                build_id=target.build_id,
                root_frame_id=target.root_frame_id or target.frame_id,
                parent_frame_id=target.frame_id,
                depth=target.depth + 1,
                skeleton_build_id=target.skeleton_build_id,
                skeleton_generation=target.skeleton_generation,
                folder_node_id=child_node_id,
                folder_stable_ref=child_stable_ref,
                folder_path=str(child.get("path") or ""),
                budget=target.budget,
                metadata={
                    "parent_folder_ref": target.folder_stable_ref,
                    "algorithm_kind": "tree_reduce",
                    "authority_boundary": "child_frame_from_directory_manifest",
                },
            )
            child_frames.append(self.project_network_repository.upsert_directory_frame(child_frame))
        if child_frames:
            self.project_network_repository.upsert_directory_frame(
                replace(
                    target,
                    child_frame_ids=tuple(item.frame_id for item in child_frames),
                    status="child_frames_created",
                )
            )
        return tuple(child_frames)

    def register_child_return(
        self,
        *,
        build_id: str,
        parent_frame_id: str,
        child_frame_id: str,
        child_summary_product_ref: str,
        status: str = "candidate",
        payload_ref: str = "",
        coverage: dict[str, Any] | None = None,
        blockers: tuple[str, ...] | list[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> DirectoryChildReturnEnvelope:
        child_frame = self.project_network_repository.get_directory_frame(child_frame_id)
        if child_frame is None:
            raise KeyError(f"child directory frame not found: {child_frame_id}")
        if child_frame.parent_frame_id and child_frame.parent_frame_id != parent_frame_id:
            raise ValueError(f"child directory frame parent mismatch: {child_frame_id}")
        return_id = stable_project_network_id("pndirret", build_id, parent_frame_id, child_frame_id, child_summary_product_ref)
        envelope = DirectoryChildReturnEnvelope(
            return_id=return_id,
            build_id=build_id,
            parent_frame_id=parent_frame_id,
            child_frame_id=child_frame_id,
            child_folder_ref=child_frame.folder_stable_ref,
            child_folder_node_id=child_frame.folder_node_id,
            child_summary_product_ref=child_summary_product_ref,
            status=status,
            payload_ref=payload_ref,
            coverage=dict(coverage or {}),
            blockers=tuple(str(item) for item in blockers if str(item)),
            metadata={
                **dict(metadata or {}),
                "source_child_frame_status": child_frame.status,
            },
        )
        stored = self.project_network_repository.upsert_directory_child_return(envelope)
        if child_frame.parent_frame_id:
            self.project_network_repository.upsert_directory_frame(
                replace(
                    child_frame,
                    aggregate_work_product_ref=child_summary_product_ref or child_frame.aggregate_work_product_ref,
                    status="returned_to_parent",
                )
            )
        parent = self.project_network_repository.get_directory_frame(parent_frame_id)
        if parent is not None:
            next_child_return_refs = tuple(dict.fromkeys((*parent.child_return_refs, stored.return_id)))
            returned_child_ids = {
                item.child_frame_id
                for item in self.project_network_repository.list_directory_child_returns(
                    build_id=build_id,
                    parent_frame_id=parent_frame_id,
                )
                if item.child_frame_id and item.status not in {"rejected", "blocked", "failed"}
            }
            expected_child_ids = set(parent.child_frame_ids)
            next_status = parent.status
            if expected_child_ids and parent.status not in {
                "aggregating",
                "summarized",
                "returned_to_parent",
                "blocked_missing_skeleton",
                "blocked_child_failed",
                "blocked_unresolved_conflict",
                "needs_human_review",
                "cancelled",
            }:
                next_status = "ready_to_aggregate" if expected_child_ids.issubset(returned_child_ids) else "waiting_child_returns"
            self.project_network_repository.upsert_directory_frame(
                replace(
                    parent,
                    child_return_refs=next_child_return_refs,
                    status=next_status,
                )
            )
        return stored

    def build_materialization_package(
        self,
        frame: DirectoryRenderFrame | str,
        *,
        source_work_product_refs: tuple[str, ...] | list[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> DirectoryFrameMaterializationPackage:
        target = self._frame(frame)
        manifest = self.project_network_repository.get_directory_manifest(target.manifest_ref) if target.manifest_ref else None
        if manifest is None:
            manifest = self.materialize_manifest(target)
            target = self._frame(target.frame_id)
        child_returns = self.project_network_repository.list_directory_child_returns(
            build_id=target.build_id,
            parent_frame_id=target.frame_id,
        )
        child_returns = _current_child_returns_for_materialization(
            target,
            child_returns,
            repository=self.project_network_repository,
        )
        package_id = stable_project_network_id("pndirpkg", target.build_id, target.frame_id, manifest.content_hash, [item.return_id for item in child_returns])
        graph_id = f"graph.project_network.directory.{_slug(target.build_id)}.{_slug(target.frame_id)}"
        stable_frame = _stable_frame_for_materialization(target)
        stable_manifest = _stable_manifest_for_materialization(manifest)
        stable_child_returns = tuple(_stable_child_return_for_materialization(item) for item in child_returns)
        return DirectoryFrameMaterializationPackage(
            package_id=package_id,
            build_id=target.build_id,
            frame=stable_frame,
            manifest=stable_manifest,
            child_returns=stable_child_returns,
            graph_id=graph_id,
            source_work_product_refs=tuple(str(item) for item in source_work_product_refs if str(item)),
            metadata={
                **dict(metadata or {}),
                "materialization_mode": "directory_tree_reduce_frame",
                "loop_algorithm_kind": "tree_reduce",
            },
        )

    def projection(self, frame: DirectoryRenderFrame | str) -> DirectoryRenderProjection:
        target = self._frame(frame)
        manifest = self.project_network_repository.get_directory_manifest(target.manifest_ref) if target.manifest_ref else None
        child_frames = tuple(
            item
            for frame_id in target.child_frame_ids
            for item in (self.project_network_repository.get_directory_frame(frame_id),)
            if item is not None
        )
        child_returns = self.project_network_repository.list_directory_child_returns(
            build_id=target.build_id,
            parent_frame_id=target.frame_id,
        )
        expected_child_returns = len(child_frames)
        blockers: list[str] = []
        if target.status == "blocked_missing_skeleton":
            blockers.append("blocked_missing_skeleton")
        if expected_child_returns and len(child_returns) < expected_child_returns:
            blockers.append("waiting_child_returns")
        if manifest is None:
            next_action = "materialize_manifest"
        elif not child_frames and manifest.child_folder_refs:
            next_action = "create_child_frames"
        elif blockers:
            next_action = "wait"
        else:
            next_action = "materialize_frame_graph"
        return DirectoryRenderProjection(
            build_id=target.build_id,
            frame=target,
            manifest=manifest,
            child_frames=child_frames,
            child_returns=child_returns,
            next_action=next_action,
            ready_to_materialize=next_action == "materialize_frame_graph",
            blockers=tuple(blockers),
        )

    def _frame(self, frame: DirectoryRenderFrame | str) -> DirectoryRenderFrame:
        if isinstance(frame, DirectoryRenderFrame):
            return frame
        target = self.project_network_repository.get_directory_frame(str(frame or ""))
        if target is None:
            raise KeyError(f"directory render frame not found: {frame}")
        return target

    def _direct_child_nodes(self, *, frame: DirectoryRenderFrame, edge_kind: str) -> tuple[SkeletonNodeRecord, ...]:
        edges = self.project_structure_repository.list_skeleton_edges(
            build_id=frame.skeleton_build_id,
            generation=frame.skeleton_generation,
            edge_kind=edge_kind,
            src_node_id=frame.folder_node_id,
            freshness="fresh",
            limit=max(frame.budget.max_child_folders_per_frame, frame.budget.max_direct_files_per_frame) * 4,
        )
        nodes: list[SkeletonNodeRecord] = []
        for edge in edges:
            if not edge.dst_node_id:
                continue
            node = self.project_structure_repository.get_skeleton_node(edge.dst_node_id)
            if node is None or node.status != "active":
                continue
            nodes.append(node)
        return tuple(sorted(nodes, key=lambda item: (item.path.lower(), item.stable_ref)))


def _filter_child_folders(
    nodes: tuple[SkeletonNodeRecord, ...],
    *,
    budget: DirectoryRenderBudget,
) -> tuple[tuple[SkeletonNodeRecord, ...], tuple[str, ...]]:
    skipped_names = {item.lower() for item in budget.skipped_directory_names}
    accepted: list[SkeletonNodeRecord] = []
    skipped: list[str] = []
    for node in nodes:
        name = (Path(node.path).name or node.display_name or node.stable_ref).lower()
        parts = {part.lower() for part in normalize_rel_path(node.path).split("/") if part}
        if name in skipped_names or parts.intersection(skipped_names):
            skipped.append(node.stable_ref)
            continue
        if len(accepted) >= budget.max_child_folders_per_frame:
            skipped.append(node.stable_ref)
            continue
        accepted.append(node)
    return tuple(accepted), tuple(skipped)


def _filter_direct_files(
    nodes: tuple[SkeletonNodeRecord, ...],
    *,
    budget: DirectoryRenderBudget,
) -> tuple[tuple[SkeletonNodeRecord, ...], tuple[str, ...]]:
    extensions = {item.lower() for item in budget.code_file_extensions}
    accepted: list[SkeletonNodeRecord] = []
    skipped: list[str] = []
    for node in nodes:
        suffix = str(dict(node.payload or {}).get("suffix") or Path(node.path).suffix or "").lower()
        if not budget.include_non_code_files and suffix not in extensions:
            skipped.append(node.stable_ref)
            continue
        if len(accepted) >= budget.max_direct_files_per_frame:
            skipped.append(node.stable_ref)
            continue
        accepted.append(node)
    return tuple(accepted), tuple(skipped)


def _node_card(node: SkeletonNodeRecord) -> dict[str, Any]:
    payload = dict(node.payload or {})
    return {
        "node_id": node.node_id,
        "stable_ref": node.stable_ref,
        "node_kind": node.node_kind,
        "display_name": node.display_name,
        "path": node.path,
        "layer_kind": node.layer_kind,
        "hierarchy_path": node.hierarchy_path,
        "anchor_ref": node.anchor_ref,
        "file_hash": node.file_hash,
        "payload": {
            key: payload.get(key)
            for key in ("suffix", "size_bytes", "physical_layer", "child_counts")
            if payload.get(key) not in ("", None, [], {})
        },
        "authority": "task_system.project_network.directory_render_service.skeleton_node_card",
    }


def _stable_frame_for_materialization(frame: DirectoryRenderFrame) -> DirectoryRenderFrame:
    return replace(
        frame,
        graph_id="",
        graph_run_id="",
        status="ready_to_aggregate",
        created_at="",
        updated_at="",
        metadata=_stable_metadata(dict(frame.metadata or {})),
    )


def _stable_manifest_for_materialization(manifest: DirectoryManifestProduct) -> DirectoryManifestProduct:
    return replace(
        manifest,
        created_at="",
        updated_at="",
        metadata=_stable_metadata(dict(manifest.metadata or {})),
    )


def _stable_child_return_for_materialization(child_return: DirectoryChildReturnEnvelope) -> DirectoryChildReturnEnvelope:
    return replace(
        child_return,
        created_at="",
        updated_at="",
        metadata=_stable_metadata(dict(child_return.metadata or {})),
    )


def _current_child_returns_for_materialization(
    frame: DirectoryRenderFrame,
    child_returns: tuple[DirectoryChildReturnEnvelope, ...],
    *,
    repository: ProjectNetworkRepository,
) -> tuple[DirectoryChildReturnEnvelope, ...]:
    if not child_returns:
        return ()
    by_child_frame: dict[str, list[DirectoryChildReturnEnvelope]] = {}
    for item in child_returns:
        if item.status in {"rejected", "blocked", "failed"}:
            continue
        if item.child_frame_id:
            by_child_frame.setdefault(item.child_frame_id, []).append(item)

    selected: list[DirectoryChildReturnEnvelope] = []
    selected_ids: set[str] = set()
    expected_child_ids = set(frame.child_frame_ids)
    for child_frame_id in frame.child_frame_ids:
        candidates = by_child_frame.get(child_frame_id) or []
        if not candidates:
            continue
        child_frame = repository.get_directory_frame(child_frame_id)
        current_product_ref = str(getattr(child_frame, "aggregate_work_product_ref", "") or "")
        if current_product_ref:
            current = [item for item in candidates if item.child_summary_product_ref == current_product_ref]
            if current:
                selected.append(current[0])
                selected_ids.add(current[0].return_id)
                continue
        selected.append(candidates[0])
        selected_ids.add(candidates[0].return_id)

    for child_frame_id, candidates in by_child_frame.items():
        if child_frame_id in expected_child_ids:
            continue
        for candidate in candidates:
            if candidate.return_id in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(candidate.return_id)
            break
    return tuple(selected)


def _stable_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    volatile_prefixes = ("latest_", "runtime_", "start_", "publish_")
    volatile_keys = {
        "graph_run_id",
        "graph_config_id",
        "graph_config_hash",
        "updated_at",
        "created_at",
        "source_graph_run_id",
        "source_payload_ref",
    }
    return {
        str(key): value
        for key, value in metadata.items()
        if str(key)
        and not str(key).startswith(volatile_prefixes)
        and str(key) not in volatile_keys
    }


def _slug(value: str) -> str:
    return ".".join(
        part
        for part in str(value or "").replace(":", ".").replace("/", ".").replace("\\", ".").replace("_", ".").replace("-", ".").split(".")
        if part
    )
