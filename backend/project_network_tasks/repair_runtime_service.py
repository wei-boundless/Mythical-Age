from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout
from file_management.project_structure.repository import ProjectStructureRepository
from file_management.project_structure.skeleton_refs import file_ref, folder_ref, normalize_rel_path
from task_system.compiler.executable_graph_config_publisher import build_graph_config_from_graph
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphNodeDefinition
from task_system.registry.flow_registry import TaskFlowRegistry

from project_network_system.directory_render_models import (
    DirectoryFrameMaterializationPackage,
    DirectoryManifestProduct,
    DirectoryRenderFrame,
)
from project_network_system.repository import ProjectNetworkRepository, content_hash, stable_project_network_id
from project_network_system.service import ProjectNetworkBuildService, ProjectNetworkWorkProductIngestResult
from project_network_system.store_models import ProjectNetworkRepairWorkItemRecord

from .directory_render_service import DirectoryRenderService
from .directory_runtime_service import DirectoryRuntimeService
from .graph_builder import ProjectNetworkGraphBuilder
from .repair_run_models import ProjectNetworkRepairGraphPublishResult


@dataclass(frozen=True, slots=True)
class _ResolvedRepairItem:
    item: ProjectNetworkRepairWorkItemRecord
    folder_stable_ref: str
    selected_file_refs: tuple[str, ...]
    resolved_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _RepairBatchPlan:
    build_id: str
    repair_batch_id: str
    folder_stable_ref: str
    repair_items: tuple[ProjectNetworkRepairWorkItemRecord, ...]
    selected_file_refs: tuple[str, ...]
    deferred_repair_item_ids: tuple[str, ...]
    frame: DirectoryRenderFrame
    manifest: DirectoryManifestProduct
    child_return_refs: tuple[str, ...]
    source_work_product_refs: tuple[str, ...]
    item_file_map: dict[str, tuple[str, ...]]
    metadata: dict[str, Any]


class ProjectNetworkRepairRuntimeService:
    authority = "project_network_tasks.repair_runtime_service"

    def __init__(
        self,
        *,
        target_base_dir: str | Path,
        runtime_base_dir: str | Path,
        repository: ProjectNetworkRepository,
        project_structure_repository: ProjectStructureRepository,
        directory_render_service: DirectoryRenderService,
        directory_runtime_service: DirectoryRuntimeService,
        build_service: ProjectNetworkBuildService,
        graph_builder: ProjectNetworkGraphBuilder | None = None,
        flow_registry: TaskFlowRegistry | None = None,
    ) -> None:
        self.target_base_dir = Path(target_base_dir).resolve()
        self.runtime_base_dir = Path(runtime_base_dir).resolve()
        self.repository = repository
        self.project_structure_repository = project_structure_repository
        self.directory_render_service = directory_render_service
        self.directory_runtime_service = directory_runtime_service
        self.build_service = build_service
        self.graph_builder = graph_builder or ProjectNetworkGraphBuilder()
        if flow_registry is None:
            raise ValueError("ProjectNetworkRepairRuntimeService requires TaskFlowRegistry")
        self.flow_registry = flow_registry

    @classmethod
    def from_backend_dir(
        cls,
        base_dir: str | Path,
        *,
        flow_registry_base_dir: str | Path | None = None,
    ) -> "ProjectNetworkRepairRuntimeService":
        target_root = Path(base_dir).resolve()
        runtime_root = Path(flow_registry_base_dir).resolve() if flow_registry_base_dir is not None else target_root
        repository = ProjectNetworkRepository(target_root)
        project_structure_repository = ProjectStructureRepository(target_root)
        directory_render_service = DirectoryRenderService(
            project_structure_repository=project_structure_repository,
            project_network_repository=repository,
        )
        build_service = ProjectNetworkBuildService(repository)
        return cls(
            target_base_dir=target_root,
            runtime_base_dir=runtime_root,
            repository=repository,
            project_structure_repository=project_structure_repository,
            directory_render_service=directory_render_service,
            directory_runtime_service=DirectoryRuntimeService(
                directory_render_service=directory_render_service,
                build_service=build_service,
                flow_registry=TaskFlowRegistry(runtime_root),
            ),
            build_service=build_service,
            flow_registry=TaskFlowRegistry(runtime_root),
        )

    def publish_repair_graph(
        self,
        *,
        build_id: str = "",
        repair_item_ids: tuple[str, ...] | list[str] = (),
        status: str = "queued",
        limit: int = 4,
        publish_version: str = "runtime",
        runtime_scope: dict[str, Any] | None = None,
        max_active_nodes: int = 0,
    ) -> ProjectNetworkRepairGraphPublishResult:
        plan = self._plan_repair_batch(
            build_id=build_id,
            repair_item_ids=repair_item_ids,
            status=status,
            limit=limit,
            max_active_nodes=max_active_nodes,
        )
        child_returns = self._child_returns_for_frame(plan.frame.frame_id)
        package = DirectoryFrameMaterializationPackage(
            package_id=stable_project_network_id(
                "pnrepairpkg",
                plan.build_id,
                plan.repair_batch_id,
                plan.folder_stable_ref,
                list(plan.selected_file_refs),
                list(plan.source_work_product_refs),
            ),
            build_id=plan.build_id,
            frame=plan.frame,
            manifest=plan.manifest,
            child_returns=child_returns,
            graph_id=f"graph.project_network.repair.{_slug(plan.build_id)}.{_slug(plan.repair_batch_id)}",
            source_work_product_refs=plan.source_work_product_refs,
            metadata={
                **dict(plan.metadata or {}),
                **_target_project_metadata(self.target_base_dir),
                "materialization_mode": "directory_tree_reduce_repair_batch",
                "repair_batch_id": plan.repair_batch_id,
                "repair_item_ids": [item.repair_item_id for item in plan.repair_items],
            },
        )
        task_graph = self.graph_builder.build_directory_frame_graph(package)
        task_graph = self._decorate_repair_graph(
            task_graph,
            repair_batch_id=plan.repair_batch_id,
            repair_items=plan.repair_items,
            item_file_map=plan.item_file_map,
            selected_file_refs=plan.selected_file_refs,
            max_active_nodes=max_active_nodes,
        )
        stored_graph = self._publish_task_graph(task_graph)
        graph_config = build_graph_config_from_graph(
            graph=stored_graph,
            publish_version=publish_version,
            graph_lookup=self.flow_registry,
            base_dir=self.flow_registry.base_dir,
        )
        stored_config = self.flow_registry.upsert_graph_config(graph_config, publish=True)
        start_initial_inputs = self.repair_graph_start_initial_inputs(
            repair_batch_id=plan.repair_batch_id,
            repair_items=plan.repair_items,
            package=package,
            runtime_scope=runtime_scope,
        )
        self._mark_repair_items(
            plan.repair_items,
            status="published",
            metadata={
                "latest_repair_batch_id": plan.repair_batch_id,
                "latest_repair_graph_id": stored_graph.graph_id,
                "latest_repair_graph_config_id": stored_config.config_id,
                "latest_repair_folder_ref": plan.folder_stable_ref,
                "latest_repair_selected_file_refs": list(plan.selected_file_refs),
                "latest_repair_publish_authority": self.authority,
            },
        )
        self._mark_trigger_signals(plan.repair_items, status="dispatched")
        return ProjectNetworkRepairGraphPublishResult(
            build_id=plan.build_id,
            repair_batch_id=plan.repair_batch_id,
            folder_stable_ref=plan.folder_stable_ref,
            selected_file_refs=plan.selected_file_refs,
            deferred_repair_item_ids=plan.deferred_repair_item_ids,
            repair_items=plan.repair_items,
            package=package,
            task_graph=stored_graph,
            graph_config=stored_config,
            start_initial_inputs=start_initial_inputs,
            metadata={
                "source_work_product_refs": list(plan.source_work_product_refs),
                "child_return_ref_count": len(child_returns),
                "selected_repair_count": len(plan.repair_items),
                "deferred_repair_count": len(plan.deferred_repair_item_ids),
                "authority": self.authority,
            },
        )

    def repair_graph_start_initial_inputs(
        self,
        *,
        repair_batch_id: str,
        repair_items: tuple[ProjectNetworkRepairWorkItemRecord, ...] | list[ProjectNetworkRepairWorkItemRecord],
        package: DirectoryFrameMaterializationPackage,
        runtime_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        items = tuple(repair_items or ())
        return {
            "project_network_build_id": package.build_id,
            "directory_frame_id": package.frame.frame_id,
            "directory_frame_package": package.to_dict(),
            "project_network_repair_batch_id": str(repair_batch_id or ""),
            "project_network_repair_item_ids": [item.repair_item_id for item in items],
            "project_network_repair_folder_ref": package.frame.folder_stable_ref,
            "project_network_repair_selected_file_refs": list(package.manifest.direct_file_refs),
            "runtime_scope": _runtime_scope_for_repair_frame(package.frame, dict(runtime_scope or {})),
        }

    def record_repair_graph_start(
        self,
        *,
        repair_item_ids: tuple[str, ...] | list[str],
        repair_batch_id: str,
        graph_run_id: str,
        graph_config_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[ProjectNetworkRepairWorkItemRecord, ...]:
        items = self._load_repair_items_by_id(repair_item_ids)
        if not items:
            return ()
        self._mark_trigger_signals(items, status="running")
        return self._mark_repair_items(
            items,
            status="running",
            metadata={
                "latest_repair_batch_id": str(repair_batch_id or ""),
                "latest_repair_graph_run_id": str(graph_run_id or ""),
                "latest_repair_graph_config_id": str(graph_config_id or ""),
                **dict(metadata or {}),
            },
        )

    def record_repair_graph_terminal(
        self,
        *,
        repair_item_ids: tuple[str, ...] | list[str],
        repair_batch_id: str,
        graph_run_id: str,
        terminal_status: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[ProjectNetworkRepairWorkItemRecord, ...]:
        items = self._load_repair_items_by_id(repair_item_ids)
        if not items:
            return ()
        normalized = str(terminal_status or "").strip().lower()
        next_status = "completed" if normalized == "completed" else "failed" if normalized in {"failed", "error", "blocked"} else normalized or "completed"
        updated = self._mark_repair_items(
            items,
            status=next_status,
            metadata={
                "latest_repair_batch_id": str(repair_batch_id or ""),
                "latest_repair_graph_run_id": str(graph_run_id or ""),
                "latest_terminal_status": normalized or next_status,
                **dict(metadata or {}),
            },
        )
        self._refresh_trigger_signal_status(updated, completed=next_status == "completed")
        return updated

    def accept_repair_node_result(
        self,
        node_result: Any,
        *,
        repair_item_ids: tuple[str, ...] | list[str] = (),
        repair_batch_id: str = "",
        frame_id: str = "",
        build_id: str = "",
        default_shard_id: str = "",
        default_layer_id: str = "",
    ) -> ProjectNetworkWorkProductIngestResult:
        ingest = self.directory_runtime_service.accept_directory_node_result(
            node_result,
            frame_id=frame_id,
            build_id=build_id,
            default_shard_id=default_shard_id,
            default_layer_id=default_layer_id,
        )
        items = self._load_repair_items_by_id(repair_item_ids)
        if not items or not ingest.work_products:
            return ingest
        updated = self._mark_repair_items(
            items,
            status="ingested",
            metadata={
                "latest_repair_batch_id": str(repair_batch_id or ""),
                "latest_ingest_graph_run_id": str(ingest.graph_run_id or ""),
                "latest_ingest_node_id": str(ingest.node_id or ""),
                "latest_ingested_work_product_ids": [item.work_product_id for item in ingest.work_products],
            },
        )
        return replace(
            ingest,
            metadata={
                **dict(ingest.metadata or {}),
                "repair_item_ids": [item.repair_item_id for item in updated],
                "repair_item_count": len(updated),
                "repair_batch_id": str(repair_batch_id or ""),
                "authority": self.authority,
            },
        )

    def _plan_repair_batch(
        self,
        *,
        build_id: str,
        repair_item_ids: tuple[str, ...] | list[str],
        status: str,
        limit: int,
        max_active_nodes: int,
    ) -> _RepairBatchPlan:
        requested_ids = tuple(str(item).strip() for item in list(repair_item_ids or ()) if str(item).strip())
        items = self._load_candidate_repair_items(build_id=build_id, repair_item_ids=requested_ids, status=status, limit=limit)
        if not items:
            raise RuntimeError("no project-network repair items available for dispatch")
        resolved = tuple(self._resolve_repair_item(item) for item in items)
        primary = next((item for item in resolved if item.folder_stable_ref or item.selected_file_refs), None)
        if primary is None:
            raise RuntimeError("repair items could not be resolved to a folder or file scope")
        selected: list[_ResolvedRepairItem] = []
        deferred: list[str] = []
        for candidate in resolved:
            if candidate.folder_stable_ref != primary.folder_stable_ref:
                deferred.append(candidate.item.repair_item_id)
                continue
            if len(selected) >= max(1, int(limit or 1)):
                deferred.append(candidate.item.repair_item_id)
                continue
            selected.append(candidate)
        if not selected:
            raise RuntimeError("no compatible repair items found for a single folder-scoped repair graph")
        frame, manifest = self._frame_and_manifest_for_folder(
            build_id=primary.item.build_id,
            folder_stable_ref=primary.folder_stable_ref,
        )
        selected_file_refs = _dedupe_strings(
            [
                *[
                    ref
                    for item in selected
                    for ref in item.selected_file_refs
                ],
            ]
        )
        if not selected_file_refs:
            selected_file_refs = list(manifest.direct_file_refs)
        if not selected_file_refs:
            raise RuntimeError(f"repair batch has no direct file refs to refresh under {primary.folder_stable_ref}")
        selected_file_nodes = [
            dict(card)
            for card in list(manifest.direct_file_nodes or ())
            if str(dict(card).get("stable_ref") or "") in set(selected_file_refs)
        ]
        if len(selected_file_nodes) < len(selected_file_refs):
            selected_file_nodes.extend(
                self._fallback_file_cards(
                    build_id=primary.item.build_id,
                    file_refs=tuple(ref for ref in selected_file_refs if ref not in {str(dict(card).get("stable_ref") or "") for card in selected_file_nodes}),
                    folder_stable_ref=primary.folder_stable_ref,
                    frame=frame,
                )
            )
        selected_file_refs = _dedupe_strings([str(dict(card).get("stable_ref") or "") for card in selected_file_nodes if str(dict(card).get("stable_ref") or "")])
        if not selected_file_refs:
            raise RuntimeError(f"repair batch could not materialize file cards for {primary.folder_stable_ref}")
        targeted_manifest = replace(
            manifest,
            direct_file_node_ids=tuple(str(dict(card).get("node_id") or "") for card in selected_file_nodes if str(dict(card).get("node_id") or "")),
            direct_file_refs=tuple(selected_file_refs),
            direct_file_nodes=tuple(selected_file_nodes),
            content_hash=content_hash(
                {
                    "frame_id": frame.frame_id,
                    "folder_stable_ref": frame.folder_stable_ref,
                    "selected_file_refs": list(selected_file_refs),
                    "repair_item_ids": [item.item.repair_item_id for item in selected],
                }
            ),
            metadata={
                **dict(manifest.metadata or {}),
                "repair_batch_selected_file_refs": list(selected_file_refs),
                "repair_batch_id": stable_project_network_id(
                    "pnrepairbatch",
                    primary.item.build_id,
                    primary.folder_stable_ref,
                    [item.item.repair_item_id for item in selected],
                    list(selected_file_refs),
                ),
            },
        )
        targeted_frame = replace(
            frame,
            direct_file_refs=tuple(selected_file_refs),
            metadata={
                **dict(frame.metadata or {}),
                "repair_batch_selected_file_refs": list(selected_file_refs),
            },
        )
        source_work_product_refs = self._source_work_product_refs_for_repair(
            build_id=primary.item.build_id,
            frame=frame,
            selected_file_refs=tuple(selected_file_refs),
        )
        repair_batch_id = str(targeted_manifest.metadata.get("repair_batch_id") or "").strip()
        return _RepairBatchPlan(
            build_id=primary.item.build_id,
            repair_batch_id=repair_batch_id,
            folder_stable_ref=primary.folder_stable_ref,
            repair_items=tuple(item.item for item in selected),
            selected_file_refs=tuple(selected_file_refs),
            deferred_repair_item_ids=tuple(dict.fromkeys(deferred)),
            frame=targeted_frame,
            manifest=targeted_manifest,
            child_return_refs=tuple(item.return_id for item in self._child_returns_for_frame(frame.frame_id)),
            source_work_product_refs=tuple(source_work_product_refs),
            item_file_map={item.item.repair_item_id: item.selected_file_refs for item in selected},
            metadata={
                **_target_project_metadata(self.target_base_dir),
                "max_active_nodes": int(max_active_nodes or 0),
            },
        )

    def _load_candidate_repair_items(
        self,
        *,
        build_id: str,
        repair_item_ids: tuple[str, ...],
        status: str,
        limit: int,
    ) -> tuple[ProjectNetworkRepairWorkItemRecord, ...]:
        if repair_item_ids:
            candidates = self.repository.list_repair_items(build_id=build_id, limit=max(len(repair_item_ids) * 8, 256))
            index = {item.repair_item_id: item for item in candidates}
            return tuple(index[item_id] for item_id in repair_item_ids if item_id in index)
        resolved_status = str(status or "queued").strip()
        return self.repository.list_repair_items(
            build_id=build_id,
            status=resolved_status,
            limit=max(max(1, int(limit or 1)) * 8, 128),
        )

    def _resolve_repair_item(self, item: ProjectNetworkRepairWorkItemRecord) -> _ResolvedRepairItem:
        refs = _dedupe_strings(
            [
                str(item.subject_ref or ""),
                str(item.stable_ref or ""),
                *list(item.scope_refs or ()),
                str(dict(item.payload or {}).get("edge_id") or ""),
                str(dict(item.payload or {}).get("anchor_ref") or ""),
            ]
        )
        selected_file_refs: list[str] = []
        folder_candidates: list[str] = []
        resolved_refs: list[str] = []
        for raw_ref in refs:
            normalized = _normalize_route_like_ref(raw_ref)
            if not normalized:
                continue
            resolved_refs.append(normalized)
            if normalized.startswith("file://"):
                selected_file_refs.append(normalized)
                folder_candidates.append(_folder_ref_for_file_ref(normalized))
                continue
            if normalized.startswith("folder://"):
                folder_candidates.append(normalized)
                continue
            file_candidate = self._file_ref_from_symbolic_ref(normalized)
            if file_candidate:
                selected_file_refs.append(file_candidate)
                folder_candidates.append(_folder_ref_for_file_ref(file_candidate))
        folder_stable_ref = self._preferred_folder_ref(item=item, folder_candidates=folder_candidates, selected_file_refs=tuple(selected_file_refs))
        return _ResolvedRepairItem(
            item=item,
            folder_stable_ref=folder_stable_ref,
            selected_file_refs=tuple(_dedupe_strings(selected_file_refs)),
            resolved_refs=tuple(_dedupe_strings(resolved_refs)),
        )

    def _preferred_folder_ref(
        self,
        *,
        item: ProjectNetworkRepairWorkItemRecord,
        folder_candidates: list[str],
        selected_file_refs: tuple[str, ...],
    ) -> str:
        explicit_folder = _normalize_route_like_ref(str(item.subject_ref or "")) or _normalize_route_like_ref(str(item.stable_ref or ""))
        if explicit_folder.startswith("folder://"):
            return explicit_folder
        if folder_candidates:
            counts: dict[str, int] = {}
            for ref in folder_candidates:
                counts[ref] = counts.get(ref, 0) + 1
            return sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))[0][0]
        if selected_file_refs:
            return _folder_ref_for_file_ref(selected_file_refs[0])
        raise RuntimeError(f"repair item has no resolvable folder scope: {item.repair_item_id}")

    def _file_ref_from_symbolic_ref(self, ref: str) -> str:
        normalized = str(ref or "").strip()
        if not normalized:
            return ""
        if normalized.startswith("file://"):
            return normalized
        if normalized.startswith("pyast://"):
            return file_ref(normalized.split("://", 1)[1].split("#", 1)[0])
        if normalized.startswith("pnsnode:"):
            node_id = normalized.split("#", 1)[0]
            node = self.project_structure_repository.get_skeleton_node(node_id)
            if node is None:
                return ""
            if str(node.stable_ref or "").startswith("file://"):
                return str(node.stable_ref or "")
            if str(node.path or "").strip():
                return file_ref(str(node.path or ""))
            return ""
        if "://" in normalized and "#" in normalized:
            maybe_path = normalized.split("://", 1)[1].split("#", 1)[0]
            if "." in Path(maybe_path).name:
                return file_ref(maybe_path)
        return ""

    def _frame_and_manifest_for_folder(
        self,
        *,
        build_id: str,
        folder_stable_ref: str,
    ) -> tuple[DirectoryRenderFrame, DirectoryManifestProduct]:
        frames = self.repository.list_directory_frames(build_id=build_id, limit=5000)
        for frame in frames:
            if frame.folder_stable_ref != folder_stable_ref:
                continue
            manifest = self.repository.get_directory_manifest(frame.manifest_ref) if frame.manifest_ref else None
            if manifest is not None:
                return frame, manifest
        folder_path = _path_from_folder_ref(folder_stable_ref)
        if not folder_path:
            raise RuntimeError(f"folder repair scope has no materialized frame: {folder_stable_ref}")
        frame = self.directory_render_service.create_root_frame(
            build_id=build_id,
            skeleton_build_id=build_id,
            skeleton_generation=self._latest_skeleton_generation(build_id),
            folder_stable_ref=folder_stable_ref,
            folder_path=folder_path,
        )
        manifest = self.directory_render_service.materialize_manifest(frame)
        return frame, manifest

    def _fallback_file_cards(
        self,
        *,
        build_id: str,
        file_refs: tuple[str, ...],
        folder_stable_ref: str,
        frame: DirectoryRenderFrame,
    ) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        generation = self._latest_skeleton_generation(build_id)
        for stable_ref in file_refs:
            node = self.project_structure_repository.find_skeleton_node(
                build_id=build_id,
                stable_ref=stable_ref,
                generation=generation,
            )
            if node is None:
                continue
            cards.append(
                {
                    "node_id": node.node_id,
                    "stable_ref": node.stable_ref,
                    "path": node.path,
                    "anchor_ref": node.anchor_ref,
                    "file_hash": node.file_hash,
                    "payload": dict(node.payload or {}),
                    "folder_stable_ref": folder_stable_ref,
                    "directory_frame_id": frame.frame_id,
                }
            )
        return cards

    def _source_work_product_refs_for_repair(
        self,
        *,
        build_id: str,
        frame: DirectoryRenderFrame,
        selected_file_refs: tuple[str, ...],
    ) -> list[str]:
        selected = set(selected_file_refs)
        product_refs: list[str] = []
        if frame.frame_id:
            products = self.repository.list_work_products(
                build_id=build_id,
                layer_id=f"directory_frame:{frame.frame_id}",
                product_kind="module_index",
                limit=4096,
            )
            by_file_ref = {str(item.stable_ref or ""): str(item.work_product_id or "") for item in products if str(item.work_product_id or "")}
            for ref in frame.direct_file_refs:
                if ref in selected:
                    continue
                if ref in by_file_ref:
                    product_refs.append(by_file_ref[ref])
            child_returns = self._child_returns_for_frame(frame.frame_id)
            product_refs.extend(
                str(item.child_summary_product_ref or "")
                for item in child_returns
                if str(item.child_summary_product_ref or "")
            )
        return _dedupe_strings(product_refs)

    def _child_returns_for_frame(self, frame_id: str) -> tuple[Any, ...]:
        if not str(frame_id or "").strip():
            return ()
        return self.repository.list_directory_child_returns(
            parent_frame_id=frame_id,
            limit=2048,
        )

    def _decorate_repair_graph(
        self,
        graph: TaskGraphDefinition,
        *,
        repair_batch_id: str,
        repair_items: tuple[ProjectNetworkRepairWorkItemRecord, ...],
        item_file_map: dict[str, tuple[str, ...]],
        selected_file_refs: tuple[str, ...],
        max_active_nodes: int,
    ) -> TaskGraphDefinition:
        item_ids = [item.repair_item_id for item in repair_items]
        target_metadata = _target_project_metadata(self.target_base_dir)
        patched_nodes: list[TaskGraphNodeDefinition] = []
        for node in graph.nodes:
            file_scope_ref = _node_file_scope_ref(node)
            relevant_item_ids = [
                item.repair_item_id
                for item in repair_items
                if not file_scope_ref or file_scope_ref in set(item_file_map.get(item.repair_item_id) or ())
            ]
            metadata = {
                **dict(node.metadata or {}),
                **target_metadata,
                "project_network_repair_batch_id": repair_batch_id,
                "project_network_repair_item_ids": relevant_item_ids or item_ids,
                "project_network_repair_selected_file_refs": list(selected_file_refs),
            }
            runtime_policy = {
                **dict(node.runtime_policy or {}),
                "project_network_repair": {
                    "repair_batch_id": repair_batch_id,
                    "repair_item_ids": relevant_item_ids or item_ids,
                    "selected_file_refs": list(selected_file_refs),
                    "authority": self.authority,
                },
            }
            patched_nodes.append(replace(node, metadata=metadata, runtime_policy=runtime_policy))
        runtime_policy = {
            **dict(graph.runtime_policy or {}),
            **({"max_active_nodes": int(max_active_nodes)} if int(max_active_nodes or 0) > 0 else {}),
            "project_network_repair": {
                "repair_batch_id": repair_batch_id,
                "repair_item_ids": item_ids,
                "selected_file_refs": list(selected_file_refs),
                "authority": self.authority,
            },
        }
        metadata = {
            **dict(graph.metadata or {}),
            **target_metadata,
            "repair_batch_id": repair_batch_id,
            "repair_item_ids": item_ids,
            "selected_file_refs": list(selected_file_refs),
            "published_from": self.authority,
            "publish_mode": "generated_repair_graph",
        }
        return replace(
            graph,
            title=f"Project network repair {repair_batch_id}",
            runtime_policy=runtime_policy,
            metadata=metadata,
            nodes=tuple(patched_nodes),
        )

    def _publish_task_graph(self, task_graph: TaskGraphDefinition) -> Any:
        return self.flow_registry.upsert_task_graph(
            graph_id=task_graph.graph_id,
            title=task_graph.title,
            domain_id=task_graph.domain_id,
            graph_kind=task_graph.graph_kind,
            entry_node_id=task_graph.entry_node_id,
            output_node_id=task_graph.output_node_id,
            nodes=tuple(node.to_dict() for node in task_graph.nodes),
            edges=tuple(edge.to_dict() for edge in task_graph.edges),
            graph_contract_id=task_graph.graph_contract_id,
            contract_bindings=dict(task_graph.contract_bindings or {}),
            default_protocol_id=task_graph.default_protocol_id,
            working_memory_policy_profile_id=task_graph.working_memory_policy_profile_id,
            working_memory_policy=dict(task_graph.working_memory_policy or {}),
            runtime_policy=dict(task_graph.runtime_policy or {}),
            context_policy=dict(task_graph.context_policy or {}),
            loop_frames=tuple(dict(item) for item in task_graph.loop_frames),
            publish_state="published",
            enabled=True,
            metadata={
                **dict(task_graph.metadata or {}),
                "published_from": self.authority,
                "publish_mode": "generated_repair_graph",
            },
        )

    def _mark_repair_items(
        self,
        items: tuple[ProjectNetworkRepairWorkItemRecord, ...] | list[ProjectNetworkRepairWorkItemRecord],
        *,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[ProjectNetworkRepairWorkItemRecord, ...]:
        stored: list[ProjectNetworkRepairWorkItemRecord] = []
        for item in items:
            current = item
            stored.append(
                self.repository.upsert_repair_item(
                    replace(
                        current,
                        status=str(status or current.status).strip() or current.status,
                        metadata={
                            **dict(current.metadata or {}),
                            **dict(metadata or {}),
                        },
                    )
                )
            )
        return tuple(stored)

    def _mark_trigger_signals(
        self,
        items: tuple[ProjectNetworkRepairWorkItemRecord, ...] | list[ProjectNetworkRepairWorkItemRecord],
        *,
        status: str,
    ) -> None:
        signal_ids = {str(item.trigger_signal_id or "") for item in items if str(item.trigger_signal_id or "").strip()}
        for signal_id in signal_ids:
            signal = self.repository.get_maintenance_signal(signal_id)
            if signal is None:
                continue
            self.repository.upsert_maintenance_signal(
                replace(
                    signal,
                    status=str(status or signal.status).strip() or signal.status,
                    metadata={
                        **dict(signal.metadata or {}),
                        "latest_repair_signal_status_authority": self.authority,
                    },
                )
            )

    def _refresh_trigger_signal_status(
        self,
        items: tuple[ProjectNetworkRepairWorkItemRecord, ...] | list[ProjectNetworkRepairWorkItemRecord],
        *,
        completed: bool,
    ) -> None:
        for item in items:
            signal_id = str(item.trigger_signal_id or "").strip()
            if not signal_id:
                continue
            signal = self.repository.get_maintenance_signal(signal_id)
            if signal is None:
                continue
            related = self.repository.list_repair_items(
                build_id=item.build_id,
                trigger_signal_id=signal_id,
                limit=256,
            )
            next_status = "resolved" if completed and all(str(candidate.status or "") == "completed" for candidate in related) else "running"
            self.repository.upsert_maintenance_signal(
                replace(
                    signal,
                    status=next_status,
                    metadata={
                        **dict(signal.metadata or {}),
                        "latest_repair_signal_status_authority": self.authority,
                    },
                )
            )

    def _load_repair_items_by_id(
        self,
        repair_item_ids: tuple[str, ...] | list[str],
    ) -> tuple[ProjectNetworkRepairWorkItemRecord, ...]:
        ids = tuple(str(item).strip() for item in list(repair_item_ids or ()) if str(item).strip())
        if not ids:
            return ()
        candidates = self.repository.list_repair_items(limit=max(len(ids) * 8, 256))
        index = {item.repair_item_id: item for item in candidates}
        return tuple(index[item_id] for item_id in ids if item_id in index)

    def _latest_skeleton_generation(self, build_id: str) -> int:
        generations = self.project_structure_repository.list_skeleton_generations(
            build_id=build_id,
            limit=4,
        )
        if generations:
            return int(generations[0].generation or 0)
        return 1


def _node_file_scope_ref(node: TaskGraphNodeDefinition) -> str:
    semantic_shard = dict(dict(node.metadata or {}).get("semantic_shard") or {})
    assigned_scope = dict(dict(semantic_shard or {}).get("assigned_scope") or dict(node.metadata or {}).get("assigned_scope") or {})
    return str(assigned_scope.get("file_stable_ref") or "").strip()


def _normalize_route_like_ref(value: str) -> str:
    raw = str(value or "").strip()
    if raw.startswith("route:"):
        raw = raw[len("route:") :]
    return raw.strip()


def _folder_ref_for_file_ref(value: str) -> str:
    raw = str(value or "").strip()
    if raw.startswith("file://"):
        raw = raw[len("file://") :]
    parent = str(Path(normalize_rel_path(raw)).parent).replace("\\", "/")
    return folder_ref("" if parent == "." else parent)


def _path_from_folder_ref(value: str) -> str:
    raw = str(value or "").strip()
    if raw.startswith("folder://"):
        raw = raw[len("folder://") :]
    return normalize_rel_path(raw)


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _slug(value: str) -> str:
    return ".".join(part for part in str(value or "").replace(":", ".").replace("/", ".").replace("\\", ".").replace("_", ".").replace("-", ".").split(".") if part)


def _runtime_scope_for_repair_frame(frame: DirectoryRenderFrame, runtime_scope: dict[str, Any]) -> dict[str, Any]:
    project_id = str(runtime_scope.get("project_id") or frame.build_id or "").strip()
    return {
        **dict(runtime_scope or {}),
        "workspace_view": str(runtime_scope.get("workspace_view") or "graph_task"),
        "project_id": project_id,
        "graph_task_instance_id": str(runtime_scope.get("graph_task_instance_id") or frame.frame_id or frame.build_id),
        "project_network_build_id": frame.build_id,
        "directory_frame_id": frame.frame_id,
        "scope_source": "project_network_tasks.repair_runtime_service",
    }


def _target_project_metadata(target_base_dir: Path) -> dict[str, str]:
    layout = ProjectLayout.from_backend_dir(target_base_dir)
    return {
        "project_network_target_backend_dir": str(layout.backend_dir),
        "project_network_target_project_root": str(layout.project_root),
    }

