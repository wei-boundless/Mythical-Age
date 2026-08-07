from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from task_system.graph_instances.file_service import GraphTaskInstanceFileService
from task_system.graph_instances.models import GraphTaskInstance
from task_system.graph_instances.repository import GraphTaskInstanceRepository
from task_system.session_scope import normalize_session_scope


GRAPH_TASK_WORKSPACE_VIEW = "graph_task"


@dataclass(frozen=True, slots=True)
class GraphTaskInstanceStartBinding:
    instance: GraphTaskInstance
    root_session: dict[str, Any]
    scope: dict[str, str]
    initial_inputs: dict[str, Any]
    created: bool
    source_project_id: str = ""


class GraphTaskInstanceLaunchService:
    authority = "task_system.graph_task_instance_launch_service"

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.repository = GraphTaskInstanceRepository(self.base_dir)
        self.files = GraphTaskInstanceFileService(self.base_dir)

    def ensure_for_graph_start(
        self,
        *,
        runtime: Any,
        graph_id: str,
        graph_title: str = "",
        launch_session_id: str = "",
        launch_scope: dict[str, Any] | None = None,
        initial_inputs: dict[str, Any] | None = None,
        source: str = "",
    ) -> GraphTaskInstanceStartBinding:
        payload = dict(initial_inputs or {})
        requested_scope = normalize_session_scope(launch_scope)
        requested_instance_id = self._requested_instance_id(payload=payload, launch_scope=requested_scope.to_dict())
        source_project_id = self._source_project_id(payload=payload, launch_scope=requested_scope.to_dict(), explicit_instance_id=requested_instance_id)
        created = False
        if requested_instance_id and self.repository.get(requested_instance_id) is not None:
            instance = self.repository.require(requested_instance_id)
            if instance.graph_id != str(graph_id or "").strip():
                raise ValueError(
                    f"graph task instance {requested_instance_id} belongs to {instance.graph_id}, not {graph_id}"
                )
            instance = self._patch_launch_metadata(
                instance=instance,
                initial_inputs=payload,
                source_project_id=source_project_id,
                source=source,
            )
        else:
            instance = self._create_instance(
                runtime=runtime,
                graph_id=graph_id,
                graph_title=graph_title,
                launch_session_id=launch_session_id,
                source_project_id=source_project_id,
                initial_inputs=payload,
                source=source,
                requested_instance_id=requested_instance_id,
            )
            created = True
        root_session = self._ensure_root_session(runtime=runtime, instance=instance)
        if str(root_session.get("id") or "") != instance.root_session_id:
            instance = self.repository.patch(instance.graph_task_instance_id, {"root_session_id": str(root_session.get("id") or "")})
        self.files.ensure_space(instance.graph_task_instance_id)
        scope = self.instance_scope(instance.graph_task_instance_id)
        return GraphTaskInstanceStartBinding(
            instance=instance,
            root_session=root_session,
            scope=scope,
            initial_inputs=self._bound_initial_inputs(
                instance=instance,
                initial_inputs=payload,
                scope=scope,
                source_project_id=source_project_id,
            ),
            created=created,
            source_project_id=source_project_id,
        )

    def record_graph_run(
        self,
        instance_id: str,
        *,
        graph_run_id: str,
        status: str = "running",
        metadata: dict[str, Any] | None = None,
    ) -> GraphTaskInstance:
        return self.repository.record_run(
            instance_id,
            graph_run_id=graph_run_id,
            status=status,
            metadata={
                "run_record_authority": self.authority,
                **dict(metadata or {}),
            },
        )

    def record_graph_run_status(
        self,
        graph_run_id: str,
        *,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> GraphTaskInstance | None:
        target = str(graph_run_id or "").strip()
        if not target:
            return None
        for instance in self.repository.list():
            if instance.active_graph_run_id == target or target in set(instance.graph_run_ids):
                return self.repository.patch(
                    instance.graph_task_instance_id,
                    {
                        "status": str(status or "").strip() or instance.status,
                        "metadata": {
                            "run_status_update_authority": self.authority,
                            **dict(metadata or {}),
                        },
                    },
                )
        return None

    @staticmethod
    def instance_scope(instance_id: str) -> dict[str, str]:
        return {
            "workspace_view": GRAPH_TASK_WORKSPACE_VIEW,
            "task_environment_id": "",
            "project_id": str(instance_id or "").strip(),
        }

    def _requested_instance_id(self, *, payload: dict[str, Any], launch_scope: dict[str, Any]) -> str:
        runtime_scope = dict(payload.get("runtime_scope") or {})
        candidates = (
            payload.get("graph_task_instance_id"),
            runtime_scope.get("graph_task_instance_id"),
            launch_scope.get("graph_task_instance_id"),
            launch_scope.get("project_id") if launch_scope.get("workspace_view") == GRAPH_TASK_WORKSPACE_VIEW else "",
        )
        for value in candidates:
            candidate = str(value or "").strip()
            if candidate:
                return _safe_instance_id(candidate)
        return ""

    def _source_project_id(self, *, payload: dict[str, Any], launch_scope: dict[str, Any], explicit_instance_id: str) -> str:
        runtime_scope = dict(payload.get("runtime_scope") or {})
        candidates = (
            launch_scope.get("project_id"),
            payload.get("source_project_id"),
            runtime_scope.get("source_project_id"),
            payload.get("project_id"),
            runtime_scope.get("project_id"),
        )
        for value in candidates:
            candidate = str(value or "").strip()
            if candidate and candidate != explicit_instance_id and self.repository.get(candidate) is None:
                return candidate
        return ""

    def _create_instance(
        self,
        *,
        runtime: Any,
        graph_id: str,
        graph_title: str,
        launch_session_id: str,
        source_project_id: str,
        initial_inputs: dict[str, Any],
        source: str,
        requested_instance_id: str = "",
    ) -> GraphTaskInstance:
        instance_id = _safe_instance_id(requested_instance_id) or self.repository.next_id(graph_id)
        scope = self.instance_scope(instance_id)
        title = _instance_title(graph_title=graph_title, initial_inputs=initial_inputs)
        root_session = runtime.session_manager.create_session(
            title=f"{title} - 图任务项目",
            scope=scope,
            session_id=f"gti-root-{_safe_session_fragment(instance_id)}",
        )
        metadata = _instance_metadata(
            graph_title=graph_title,
            launch_session_id=launch_session_id,
            source_project_id=source_project_id,
            initial_inputs=initial_inputs,
            source=source,
        )
        return self.repository.create(
            graph_id=graph_id,
            title=title,
            description=_instance_description(initial_inputs),
            root_session_id=str(root_session.get("id") or ""),
            metadata=metadata,
            instance_id=instance_id,
        )

    def _ensure_root_session(self, *, runtime: Any, instance: GraphTaskInstance) -> dict[str, Any]:
        target_session_id = instance.root_session_id or f"gti-root-{_safe_session_fragment(instance.graph_task_instance_id)}"
        if target_session_id:
            try:
                return runtime.session_manager.load_session_record(target_session_id)
            except Exception:
                pass
        return runtime.session_manager.create_session(
            title=f"{instance.title} - 图任务项目",
            scope=self.instance_scope(instance.graph_task_instance_id),
            session_id=target_session_id,
        )

    def _bound_initial_inputs(
        self,
        *,
        instance: GraphTaskInstance,
        initial_inputs: dict[str, Any],
        scope: dict[str, str],
        source_project_id: str,
    ) -> dict[str, Any]:
        payload = dict(initial_inputs or {})
        runtime_scope = {
            **dict(payload.get("runtime_scope") or {}),
            **scope,
            "graph_task_instance_id": instance.graph_task_instance_id,
            "scope_source": "task_system.graph_task_instance_launch",
        }
        for key in ("project_path", "artifact_root"):
            value = str(payload.get(key) or "").strip()
            if value:
                runtime_scope[key] = _normalize_logical_root(value)
        if source_project_id:
            payload.setdefault("source_project_id", source_project_id)
            runtime_scope["source_project_id"] = source_project_id
        payload["graph_task_instance_id"] = instance.graph_task_instance_id
        payload["workspace_view"] = GRAPH_TASK_WORKSPACE_VIEW
        payload["project_id"] = instance.graph_task_instance_id
        payload["runtime_scope"] = runtime_scope
        payload.setdefault("project_title", instance.title)
        payload.setdefault("title", instance.title)
        if str(payload.get("user_creative_seed") or "").strip():
            payload.setdefault("user_input_kind", "raw_creative_paragraph")
        return payload

    def _patch_launch_metadata(
        self,
        *,
        instance: GraphTaskInstance,
        initial_inputs: dict[str, Any],
        source_project_id: str,
        source: str,
    ) -> GraphTaskInstance:
        writing_project_patch = _writing_project_metadata(initial_inputs)
        metadata_patch: dict[str, Any] = {
            "latest_launch_source": str(source or "").strip() or "graph_task_start",
        }
        if source_project_id:
            metadata_patch["source_project_id"] = source_project_id
        if writing_project_patch:
            current = dict(instance.metadata or {})
            metadata_patch["writing_project"] = {
                **dict(current.get("writing_project") or {}),
                **writing_project_patch,
            }
            run_config = dict(current.get("run_config") or {})
            run_inputs = dict(run_config.get("initial_inputs") or {})
            run_config["initial_inputs"] = {**run_inputs, **writing_project_patch}
            metadata_patch["run_config"] = run_config
        if len(metadata_patch) <= 1 and not source_project_id:
            return instance
        return self.repository.patch(instance.graph_task_instance_id, {"metadata": metadata_patch})


def _instance_title(*, graph_title: str, initial_inputs: dict[str, Any]) -> str:
    for key in ("project_title", "title", "task_title", "name"):
        value = str(initial_inputs.get(key) or "").strip()
        if value:
            return value[:200]
    return str(graph_title or "图任务项目").strip()[:200] or "图任务项目"


def _instance_description(initial_inputs: dict[str, Any]) -> str:
    for key in ("description", "user_creative_seed", "brief"):
        value = str(initial_inputs.get(key) or "").strip()
        if value:
            return value[:2000]
    return ""


def _instance_metadata(
    *,
    graph_title: str,
    launch_session_id: str,
    source_project_id: str,
    initial_inputs: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    return {
        "graph_title": str(graph_title or "").strip(),
        "launch_session_id": str(launch_session_id or "").strip(),
        "source_project_id": str(source_project_id or "").strip(),
        "creation_source": str(source or "").strip() or "graph_task_start",
        "run_config": {"initial_inputs": dict(initial_inputs or {})},
        "writing_project": _writing_project_metadata(initial_inputs),
    }


def _writing_project_metadata(initial_inputs: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "user_creative_seed",
        "user_input_kind",
        "project_title",
        "title",
        "reference_works",
        "hard_constraints",
        "creative_constraints",
        "genre",
        "graph_task_instance_id",
        "style",
        "artifact_root",
        "project_path",
        "source_project_id",
        "target_audience",
    }
    return {
        key: value
        for key, value in dict(initial_inputs or {}).items()
        if key in allowed and str(value or "").strip()
    }


def _safe_session_fragment(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in str(value or "").strip())
    return safe.strip(".-") or "graph-task-instance"


def _safe_instance_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", ".", ":"} else "." for ch in str(value or "").strip())
    safe = ".".join(part for part in safe.strip(".:").split(".") if part)
    return safe or ""


def _normalize_logical_root(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").strip().strip("'\"`").strip("/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized
