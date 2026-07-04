from __future__ import annotations

from collections import deque
from dataclasses import replace
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout
from graph_system.models import NodeResultEnvelope
from task_system.compiler.executable_graph_config_publisher import build_graph_config_from_graph
from task_system.registry.flow_registry import TaskFlowRegistry

from project_network_system.build_contract_models import ProjectNetworkBuildContract
from project_network_system.directory_render_models import DirectoryChildReturnEnvelope, DirectoryRenderFrame
from project_network_system.repository import ProjectNetworkRepository
from project_network_system.service import ProjectNetworkBuildService, ProjectNetworkWorkProductIngestResult
from project_network_system.shard_models import ShardPlan
from project_network_system.work_product_models import GraphBuildWorkProductEnvelope, WorkProductChannel

from .directory_render_service import DirectoryRenderService
from .directory_run_models import (
    DirectoryFrameGraphPublishResult,
    DirectoryFrameSchedulerDecision,
    DirectoryFrameTreeMaterializationResult,
)
from .graph_builder import ProjectNetworkGraphBuilder


class DirectoryRuntimeService:
    """Connects directory render frames to GraphSystem execution.

    This service is orchestration glue. It may materialize frame manifests, build
    frame graphs, start GraphSystem runs, and register typed child returns. It
    must not decide semantic facts or publish semantic overlay records.
    """

    authority = "project_network_tasks.directory_runtime_service"

    def __init__(
        self,
        *,
        directory_render_service: DirectoryRenderService,
        build_service: ProjectNetworkBuildService,
        graph_builder: ProjectNetworkGraphBuilder | None = None,
        flow_registry: TaskFlowRegistry | None = None,
    ) -> None:
        self.directory_render_service = directory_render_service
        self.repository = directory_render_service.project_network_repository
        self.build_service = build_service
        self.graph_builder = graph_builder or ProjectNetworkGraphBuilder()
        if flow_registry is None:
            raise ValueError("DirectoryRuntimeService requires TaskFlowRegistry; use from_backend_dir() for default wiring")
        self.flow_registry = flow_registry

    @classmethod
    def from_backend_dir(
        cls,
        base_dir: str | Path,
        *,
        flow_registry_base_dir: str | Path | None = None,
    ) -> "DirectoryRuntimeService":
        root = Path(base_dir)
        registry_root = Path(flow_registry_base_dir) if flow_registry_base_dir is not None else root
        return cls(
            directory_render_service=DirectoryRenderService.from_backend_dir(root),
            build_service=ProjectNetworkBuildService.from_backend_dir(root),
            flow_registry=TaskFlowRegistry(registry_root),
        )

    def prepare_frame(self, frame_id: str) -> DirectoryFrameSchedulerDecision:
        """Materialize deterministic frame state needed before graph start."""

        frame = self._require_frame(frame_id)
        manifest = self.repository.get_directory_manifest(frame.manifest_ref) if frame.manifest_ref else None
        if manifest is None:
            manifest = self.directory_render_service.materialize_manifest(frame)
            frame = self._require_frame(frame.frame_id)
        if manifest.child_folder_refs and not frame.child_frame_ids:
            self.directory_render_service.create_child_frames(frame, manifest)
            frame = self._require_frame(frame.frame_id)
        self._sync_frame_wait_status(frame)
        return self.scheduler_decision(frame.frame_id)

    def materialize_frame_tree(
        self,
        root_frame_id: str,
        *,
        max_total_frames: int = 0,
    ) -> DirectoryFrameTreeMaterializationResult:
        """Materialize the deterministic physical frame tree below root_frame_id.

        This pass deliberately does not wait for semantic child returns. It walks
        the physical skeleton, creates frame manifests and child frames, and then
        reports which frames are ready for graph publication versus waiting for
        semantic reduce inputs.
        """

        root = self._require_frame(root_frame_id)
        frame_limit = max(1, int(max_total_frames or root.budget.max_total_frames or 1))
        root_tree_id = root.root_frame_id or root.frame_id
        existing_frames = self.repository.list_directory_frames(
            build_id=root.build_id,
            root_frame_id=root_tree_id,
            limit=max(frame_limit + 1, 2),
        )
        known_frame_ids = {item.frame_id for item in existing_frames}
        known_frame_ids.add(root.frame_id)
        visited_frame_ids: set[str] = set()
        queue: deque[str] = deque([root.frame_id])
        prepared_count = 0
        created_frame_ids: set[str] = set()

        while queue:
            frame_id = queue.popleft()
            if frame_id in visited_frame_ids:
                continue
            visited_frame_ids.add(frame_id)
            frame = self._require_frame(frame_id)
            manifest = self.repository.get_directory_manifest(frame.manifest_ref) if frame.manifest_ref else None
            if manifest is None:
                manifest = self.directory_render_service.materialize_manifest(frame)
                frame = self._require_frame(frame.frame_id)

            needs_child_frames = bool(manifest.child_folder_refs and frame.depth < frame.budget.max_depth)
            missing_child_refs = _missing_child_folder_refs(frame, tuple(manifest.child_folder_refs), repository=self.repository)
            if needs_child_frames and missing_child_refs:
                remaining_frame_slots = frame_limit - len(known_frame_ids)
                created_children = self.directory_render_service.create_child_frames(
                    frame,
                    manifest,
                    max_new_frames=max(0, remaining_frame_slots),
                )
                for child in created_children:
                    if child.frame_id not in known_frame_ids:
                        created_frame_ids.add(child.frame_id)
                    known_frame_ids.add(child.frame_id)
                frame = self._require_frame(frame.frame_id)

            frame = self._sync_frame_wait_status(frame)
            prepared_count += 1
            for child_frame_id in frame.child_frame_ids:
                if child_frame_id not in visited_frame_ids:
                    queue.append(child_frame_id)

        materialized_frames = tuple(
            sorted(
                (self._require_frame(frame_id) for frame_id in visited_frame_ids),
                key=lambda item: (item.depth, item.folder_path.lower(), item.frame_id),
            )
        )
        ready_frames: list[dict[str, Any]] = []
        waiting_frames: list[dict[str, Any]] = []
        blocked_frames: list[dict[str, Any]] = []
        budget_stop_frames: list[dict[str, Any]] = []
        for frame in materialized_frames:
            decision = self.scheduler_decision(frame.frame_id)
            card = _frame_tree_status_card(frame, decision=decision)
            if decision.ready_to_publish_graph:
                ready_frames.append(card)
            elif "waiting_child_returns" in decision.blockers or decision.next_action == "wait_child_returns":
                waiting_frames.append(card)
            if _has_blocker_other_than_waiting(decision.blockers):
                blocked_frames.append(card)
            if "blocked_materialization_budget_exhausted" in decision.blockers:
                budget_stop_frames.append(card)

        return DirectoryFrameTreeMaterializationResult(
            build_id=root.build_id,
            root_frame_id=root.frame_id,
            root_folder_path=root.folder_path,
            max_total_frames=frame_limit,
            frame_count=len(materialized_frames),
            prepared_frame_count=prepared_count,
            created_frame_count=len(created_frame_ids),
            ready_frame_count=len(ready_frames),
            waiting_frame_count=len(waiting_frames),
            blocked_frame_count=len(blocked_frames),
            ready_frames=tuple(ready_frames),
            waiting_frames=tuple(waiting_frames),
            blocked_frames=tuple(blocked_frames),
            budget_stop_frames=tuple(budget_stop_frames),
            metadata={
                "algorithm": "deterministic_physical_bfs_materialization",
                "physical_descent_waits_for_semantic_returns": False,
                "semantic_reduce_waits_for_child_returns": True,
                "authority": self.authority,
            },
        )

    def scheduler_decision(self, frame_id: str) -> DirectoryFrameSchedulerDecision:
        projection = self.directory_render_service.projection(frame_id)
        frame = projection.frame
        returned_child_ids = {
            item.child_frame_id
            for item in projection.child_returns
            if item.child_frame_id and item.status not in {"rejected", "blocked", "failed"}
        }
        child_frame_ids = tuple(item.frame_id for item in projection.child_frames)
        missing_child_frame_ids = tuple(frame_id for frame_id in child_frame_ids if frame_id not in returned_child_ids)
        child_frame_start_queue = tuple(
            child.frame_id
            for child in projection.child_frames
            if child.frame_id in set(missing_child_frame_ids)
            and not child.graph_run_id
            and child.status
            not in {
                "blocked_missing_skeleton",
                "blocked_child_failed",
                "blocked_unresolved_conflict",
                "needs_human_review",
                "cancelled",
                "summarized",
                "returned_to_parent",
            }
        )
        next_action = projection.next_action
        if next_action == "materialize_frame_graph":
            next_action = "publish_frame_graph"
        elif next_action == "wait" and missing_child_frame_ids:
            next_action = "start_child_frames" if child_frame_start_queue else "wait_child_returns"
        return DirectoryFrameSchedulerDecision(
            build_id=frame.build_id,
            frame_id=frame.frame_id,
            next_action=next_action,
            ready_to_publish_graph=next_action == "publish_frame_graph",
            ready_to_aggregate=next_action == "publish_frame_graph",
            child_frame_ids=child_frame_ids,
            child_frame_start_queue=child_frame_start_queue,
            missing_child_frame_ids=missing_child_frame_ids,
            child_return_refs=tuple(item.return_id for item in projection.child_returns),
            blockers=projection.blockers,
            projection=projection,
            metadata={
                "physical_authority": "file_management.project_structure.skeleton",
                "semantic_authority": "project_network.agent_work_products",
            },
        )

    def publish_frame_graph(
        self,
        frame_id: str,
        *,
        publish_version: str = "runtime",
        source_work_product_refs: tuple[str, ...] | list[str] = (),
        runtime_scope: dict[str, Any] | None = None,
        max_active_nodes: int = 0,
        auto_prepare: bool = True,
    ) -> DirectoryFrameGraphPublishResult:
        source_refs = tuple(str(item) for item in source_work_product_refs if str(item))
        decision = self.prepare_frame(frame_id) if auto_prepare else self.scheduler_decision(frame_id)
        if not decision.ready_to_publish_graph:
            raise RuntimeError(
                "directory frame is not ready to publish graph config: "
                f"{decision.frame_id} next_action={decision.next_action} blockers={list(decision.blockers)}"
            )
        package = self.directory_render_service.build_materialization_package(
            frame_id,
            source_work_product_refs=source_refs,
            metadata={
                "publish_version": publish_version,
                **_target_project_metadata(self.directory_render_service.project_network_repository.db_path),
                **({"max_active_nodes": int(max_active_nodes)} if int(max_active_nodes or 0) > 0 else {}),
            },
        )
        task_graph = self.graph_builder.build_directory_frame_graph(package)
        stored_graph = self._publish_task_graph(task_graph)
        graph_config = build_graph_config_from_graph(
            graph=stored_graph,
            publish_version=publish_version,
            graph_lookup=self.flow_registry,
            base_dir=self.flow_registry.base_dir,
        )
        stored_config = self.flow_registry.upsert_graph_config(graph_config, publish=True)
        updated_frame = self.repository.upsert_directory_frame(
            replace(
                self._require_frame(package.frame.frame_id),
                graph_id=stored_graph.graph_id,
                status="graph_published",
                metadata={
                    **dict(package.frame.metadata or {}),
                    "latest_graph_config_id": stored_config.config_id,
                    "latest_graph_config_hash": stored_config.content_hash,
                    "latest_publish_authority": self.authority,
                },
            )
        )
        projection = self.directory_render_service.projection(updated_frame.frame_id)
        start_initial_inputs = self.frame_graph_start_initial_inputs(
            updated_frame.frame_id,
            source_work_product_refs=source_refs,
            runtime_scope=runtime_scope,
            auto_prepare=False,
        )
        return DirectoryFrameGraphPublishResult(
            build_id=package.build_id,
            frame_id=updated_frame.frame_id,
            package=package,
            task_graph=stored_graph,
            graph_config=stored_config,
            projection=projection,
            start_initial_inputs=start_initial_inputs,
        )

    def frame_graph_start_initial_inputs(
        self,
        frame_id: str,
        *,
        source_work_product_refs: tuple[str, ...] | list[str] = (),
        runtime_scope: dict[str, Any] | None = None,
        auto_prepare: bool = True,
    ) -> dict[str, Any]:
        decision = self.prepare_frame(frame_id) if auto_prepare else self.scheduler_decision(frame_id)
        frame = self._require_frame(frame_id)
        if not frame.graph_id:
            raise RuntimeError(f"directory frame has no published graph_id: {frame_id}")
        source_refs = tuple(str(item) for item in source_work_product_refs if str(item))
        package = self.directory_render_service.build_materialization_package(
            frame_id,
            source_work_product_refs=source_refs,
            metadata={
                "start_payload_mode": "published_directory_frame_graph",
                **_target_project_metadata(self.directory_render_service.project_network_repository.db_path),
            },
        )
        return {
            "project_network_build_id": package.build_id,
            "directory_frame_id": package.frame.frame_id,
            "directory_frame_package": package.to_dict(),
            "directory_scheduler_decision": decision.to_dict(),
            "source_work_product_refs": list(source_refs),
            "runtime_scope": _runtime_scope_for_frame(package.frame, dict(runtime_scope or {})),
        }

    def record_frame_graph_start(
        self,
        frame_id: str,
        *,
        graph_run_id: str,
        graph_config_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> DirectoryRenderFrame:
        frame = self._require_frame(frame_id)
        run_id = str(graph_run_id or "").strip()
        if not run_id:
            raise ValueError("graph_run_id is required")
        if frame.status in {
            "summarized",
            "returned_to_parent",
            "blocked_missing_skeleton",
            "blocked_child_failed",
            "blocked_unresolved_conflict",
            "needs_human_review",
            "cancelled",
        }:
            next_status = frame.status
        else:
            next_status = "direct_file_reviews_running" if frame.direct_file_refs else "aggregating"
        return self.repository.upsert_directory_frame(
            replace(
                frame,
                graph_run_id=run_id,
                status=next_status,
                metadata={
                    **dict(frame.metadata or {}),
                    **dict(metadata or {}),
                    "latest_graph_run_id": run_id,
                    "latest_graph_config_id": str(graph_config_id or frame.metadata.get("latest_graph_config_id") or "").strip(),
                    "latest_start_record_authority": self.authority,
                },
            )
        )

    def accept_directory_node_result(
        self,
        node_result: NodeResultEnvelope | dict[str, Any],
        *,
        frame_id: str = "",
        contract: ProjectNetworkBuildContract | None = None,
        build_id: str = "",
        default_shard_id: str = "",
        default_layer_id: str = "",
        channels: tuple[WorkProductChannel, ...] | list[WorkProductChannel] | None = None,
        shard_plans: tuple[ShardPlan, ...] = (),
    ) -> ProjectNetworkWorkProductIngestResult:
        frame = self.repository.get_directory_frame(frame_id) if frame_id else None
        resolved_build_id = build_id or (frame.build_id if frame is not None else "")
        resolved_layer_id = default_layer_id or (f"directory_frame:{frame.frame_id}" if frame is not None else "")
        ingest = self.build_service.accept_node_result(
            node_result,
            contract=contract,
            build_id=resolved_build_id,
            default_shard_id=default_shard_id,
            default_layer_id=resolved_layer_id,
            channels=channels,
            shard_plans=shard_plans,
        )
        child_returns = self._register_directory_summary_returns(ingest.work_products, explicit_frame_id=frame_id)
        return replace(
            ingest,
            metadata={
                **dict(ingest.metadata or {}),
                "directory_child_returns": [item.to_dict() for item in child_returns],
                "directory_child_return_count": len(child_returns),
                "authority": self.authority,
            },
        )

    def _register_directory_summary_returns(
        self,
        products: tuple[GraphBuildWorkProductEnvelope, ...],
        *,
        explicit_frame_id: str = "",
    ) -> tuple[DirectoryChildReturnEnvelope, ...]:
        registered: list[DirectoryChildReturnEnvelope] = []
        for product in products:
            if product.product_kind != "directory_summary":
                continue
            frame = self._frame_for_directory_summary(product, explicit_frame_id=explicit_frame_id)
            if frame is None:
                continue
            self.repository.upsert_directory_frame(
                replace(
                    frame,
                    aggregate_work_product_ref=product.work_product_id,
                    status="summarized",
                    metadata={
                        **dict(frame.metadata or {}),
                        "latest_directory_summary_ref": product.work_product_id,
                        "latest_directory_summary_status": product.status,
                    },
                )
            )
            if not frame.parent_frame_id:
                continue
            child_return = self.directory_render_service.register_child_return(
                build_id=product.build_id,
                parent_frame_id=frame.parent_frame_id,
                child_frame_id=frame.frame_id,
                child_summary_product_ref=product.work_product_id,
                status=product.status,
                payload_ref=product.payload_ref,
                coverage=product.coverage,
                blockers=_summary_blockers(product),
                metadata={
                    "source_work_product_id": product.work_product_id,
                    "source_graph_run_id": product.graph_run_id,
                    "source_node_id": product.node_id,
                    "source_payload_ref": product.payload_ref,
                    "authority": self.authority,
                },
            )
            registered.append(child_return)
        return tuple(registered)

    def _frame_for_directory_summary(
        self,
        product: GraphBuildWorkProductEnvelope,
        *,
        explicit_frame_id: str = "",
    ) -> DirectoryRenderFrame | None:
        for frame_id in _candidate_frame_ids(product, explicit_frame_id=explicit_frame_id):
            frame = self.repository.get_directory_frame(frame_id)
            if frame is not None:
                return frame
        if product.graph_run_id:
            frames = self.repository.list_directory_frames(
                build_id=product.build_id,
                graph_run_id=product.graph_run_id,
                limit=2,
            )
            if len(frames) == 1:
                return frames[0]
        return None

    def _sync_frame_wait_status(self, frame: DirectoryRenderFrame) -> DirectoryRenderFrame:
        projection = self.directory_render_service.projection(frame.frame_id)
        if projection.blockers and "waiting_child_returns" in projection.blockers:
            if projection.frame.status != "waiting_child_returns":
                return self.repository.upsert_directory_frame(replace(projection.frame, status="waiting_child_returns"))
            return projection.frame
        if projection.ready_to_materialize and projection.frame.status in {"planned", "manifest_ready", "child_frames_created", "waiting_child_returns"}:
            if projection.frame.status != "ready_to_aggregate":
                return self.repository.upsert_directory_frame(replace(projection.frame, status="ready_to_aggregate"))
        return projection.frame

    def _publish_task_graph(self, task_graph: Any) -> Any:
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
                "publish_mode": "generated_directory_frame_graph",
            },
        )

    def _require_frame(self, frame_id: str) -> DirectoryRenderFrame:
        frame = self.repository.get_directory_frame(frame_id)
        if frame is None:
            raise KeyError(f"directory render frame not found: {frame_id}")
        return frame


def _candidate_frame_ids(product: GraphBuildWorkProductEnvelope, *, explicit_frame_id: str = "") -> tuple[str, ...]:
    ids: list[str] = []
    if explicit_frame_id:
        ids.append(explicit_frame_id)
    payload = dict(product.payload or {})
    metadata = dict(product.metadata or {})
    for source in (payload, metadata, dict(payload.get("parent_return_payload") or {})):
        for key in ("directory_frame_id", "frame_id", "child_frame_id"):
            value = str(source.get(key) or "").strip()
            if value:
                ids.append(value)
    if product.layer_id.startswith("directory_frame:"):
        ids.append(product.layer_id.split(":", 1)[1])
    return tuple(dict.fromkeys(ids))


def _summary_blockers(product: GraphBuildWorkProductEnvelope) -> tuple[str, ...]:
    payload = dict(product.payload or {})
    parent_return_payload = dict(payload.get("parent_return_payload") or {})
    blockers = [
        *list(payload.get("blockers") or []),
        *list(payload.get("conflicts") or []),
        *list(parent_return_payload.get("blockers") or []),
    ]
    return tuple(str(item).strip() for item in blockers if str(item).strip())


def _missing_child_folder_refs(
    frame: DirectoryRenderFrame,
    child_folder_refs: tuple[str, ...],
    *,
    repository: ProjectNetworkRepository,
) -> tuple[str, ...]:
    existing_refs = {
        child.folder_stable_ref
        for child_id in frame.child_frame_ids
        for child in (repository.get_directory_frame(child_id),)
        if child is not None and child.folder_stable_ref
    }
    return tuple(str(item) for item in child_folder_refs if str(item) and str(item) not in existing_refs)


def _frame_tree_status_card(frame: DirectoryRenderFrame, *, decision: DirectoryFrameSchedulerDecision) -> dict[str, Any]:
    projection = decision.projection
    manifest = projection.manifest if projection is not None else None
    return {
        "frame_id": frame.frame_id,
        "folder_path": frame.folder_path,
        "folder_stable_ref": frame.folder_stable_ref,
        "depth": frame.depth,
        "status": frame.status,
        "next_action": decision.next_action,
        "direct_file_count": len(tuple(manifest.direct_file_refs if manifest is not None else frame.direct_file_refs)),
        "child_frame_count": len(frame.child_frame_ids),
        "child_return_count": len(frame.child_return_refs),
        "blockers": list(decision.blockers),
    }


def _has_blocker_other_than_waiting(blockers: tuple[str, ...]) -> bool:
    return any(str(item) and str(item) != "waiting_child_returns" for item in blockers)


def _runtime_scope_for_frame(frame: DirectoryRenderFrame, runtime_scope: dict[str, Any]) -> dict[str, Any]:
    project_id = str(runtime_scope.get("project_id") or frame.build_id or "").strip()
    return {
        **dict(runtime_scope or {}),
        "workspace_view": str(runtime_scope.get("workspace_view") or "graph_task"),
        "project_id": project_id,
        "graph_task_instance_id": str(runtime_scope.get("graph_task_instance_id") or frame.root_frame_id or frame.build_id),
        "project_network_build_id": frame.build_id,
        "directory_frame_id": frame.frame_id,
        "directory_root_frame_id": frame.root_frame_id,
        "directory_parent_frame_id": frame.parent_frame_id,
        "scope_source": "project_network_tasks.directory_runtime_service",
    }


def _target_project_metadata(repository_db_path: Path) -> dict[str, str]:
    db_path = Path(repository_db_path).resolve()
    storage_root = db_path.parent.parent
    project_root = storage_root.parent
    layout = ProjectLayout.from_backend_dir(project_root)
    return {
        "project_network_target_backend_dir": str(project_root),
        "project_network_target_project_root": str(layout.project_root),
    }

