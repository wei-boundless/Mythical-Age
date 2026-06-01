from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from task_system.projects.project_lifecycle_models import ProjectLifecycleRun
from task_system.registry.flow_registry import TaskFlowRegistry
from task_system.repositories.project_instance_repository import ProjectInstanceRepository
from task_system.repositories.project_library_manifest_repository import ProjectLibraryManifestRepository
from task_system.repositories.project_lifecycle_run_repository import ProjectLifecycleRunRepository


class ProjectLifecycleService:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.project_repository = ProjectInstanceRepository(self.base_dir)
        self.manifest_repository = ProjectLibraryManifestRepository(self.base_dir)
        self.run_repository = ProjectLifecycleRunRepository(self.base_dir)
        self.registry = TaskFlowRegistry(self.base_dir)

    def list_actions(self, project_id: str) -> dict[str, Any]:
        project = self.project_repository.require(project_id)
        manifest = self.manifest_repository.require_for_project(project.project_id)
        actions = [item.to_dict() for item in manifest.lifecycle_actions if item.enabled]
        return {
            "authority": "task_system.project_lifecycle_actions",
            "project_id": project.project_id,
            "actions": actions,
            "summary": {"action_count": len(actions)},
        }

    def preview(self, *, project_id: str, action: str) -> dict[str, Any]:
        project = self.project_repository.require(project_id)
        action_spec = self._require_action(project.project_id, action)
        preview = self._preview_action(action_spec.to_dict())
        return {
            "authority": "task_system.project_lifecycle_preview",
            "project_id": project.project_id,
            "action": action_spec.action_id,
            "action_spec": action_spec.to_dict(),
            "preview": preview,
        }

    def start(self, *, project_id: str, action: str, execute: bool = False) -> dict[str, Any]:
        project = self.project_repository.require(project_id)
        action_spec = self._require_action(project.project_id, action)
        preview = self.preview(project_id=project.project_id, action=action_spec.action_id)["preview"]
        run = ProjectLifecycleRun(
            run_id=f"plrun.{_safe_id(project.project_id)}.{action_spec.action_id}.{int(time.time() * 1000)}",
            project_id=project.project_id,
            action=action_spec.action_id,
            status="previewed",
            preview=preview,
            metadata={"action_spec": action_spec.to_dict()},
            created_at=str(time.time()),
            updated_at=str(time.time()),
        )
        if execute:
            result = self._execute(run, action_spec.to_dict())
            run = ProjectLifecycleRun(
                run_id=run.run_id,
                project_id=run.project_id,
                action=run.action,
                status="completed",
                preview=run.preview,
                result=result,
                metadata=dict(run.metadata),
                created_at=run.created_at,
                updated_at=str(time.time()),
            )
        self.run_repository.upsert(run)
        return {"authority": "task_system.project_lifecycle_run_api", "run": run.to_dict()}

    def list_runs(self, project_id: str) -> dict[str, Any]:
        project = self.project_repository.require(project_id)
        runs = [item.to_dict() for item in self.run_repository.list_for_project(project.project_id)]
        return {
            "authority": "task_system.project_lifecycle_runs",
            "project_id": project.project_id,
            "runs": runs,
            "summary": {"run_count": len(runs)},
        }

    def _require_action(self, project_id: str, action_id: str):
        manifest = self.manifest_repository.require_for_project(project_id)
        normalized = str(action_id or "").strip()
        action = manifest.lifecycle_action(normalized)
        if action is None or not action.enabled:
            raise ValueError(f"unsupported project lifecycle action: {action_id}")
        return action

    def _preview_action(self, action: dict[str, Any]) -> dict[str, Any]:
        operation = str(action.get("operation") or "").strip()
        if operation == "delete_task_records_by_selector":
            selectors = dict(action.get("selectors") or {})
            safeguards = dict(action.get("safeguards") or {})
            if not any(str(selectors.get(key) or "").strip() for key in ("task_id_contains", "task_id_prefix", "task_environment_id", "environment_id", "domain_id")):
                raise ValueError("delete_task_records_by_selector requires at least one selector")
            return self._preview_delete_task_records_by_selector(
                selectors=selectors,
                safeguards=safeguards,
            )
        raise ValueError(f"unsupported project lifecycle operation: {operation}")

    def _execute(self, run: ProjectLifecycleRun, action: dict[str, Any]) -> dict[str, Any]:
        operation = str(action.get("operation") or "").strip()
        if operation != "delete_task_records_by_selector":
            raise ValueError(f"unsupported project lifecycle operation: {operation}")
        deleted: list[dict[str, Any]] = []
        for task_id in list(run.preview.get("task_ids") or []):
            try:
                deleted.append(self.registry.delete_specific_task_record(str(task_id)))
            except ValueError:
                continue
        safeguards = dict(action.get("safeguards") or {})
        return {
            "authority": "task_system.project_lifecycle_delete_task_records_result",
            "deleted_task_ids": [item.get("task_id") for item in deleted if item.get("task_id")],
            "deleted": deleted,
            "preserved": {
                "task_graphs": bool(safeguards.get("preserve_task_graphs", True)),
                "artifacts": bool(safeguards.get("preserve_artifacts", True)),
                "project_instances": bool(safeguards.get("preserve_project_instances", True)),
            },
        }

    def _preview_delete_task_records_by_selector(self, *, selectors: dict[str, Any], safeguards: dict[str, Any]) -> dict[str, Any]:
        task_ids: set[str] = set()
        if bool(selectors.get("include_assignments", True)):
            for assignment in self.registry.list_task_assignments():
                if _matches_task_selector(assignment.to_dict(), selectors):
                    task_ids.add(assignment.task_id)
        if bool(selectors.get("include_specific_task_records", True)):
            for record in self.registry.list_specific_task_records():
                if _matches_task_selector(record.to_dict(), selectors):
                    task_ids.add(record.task_id)
        flow_ids = {
            item.flow_id
            for item in self.registry.list_flows()
            if str(item.metadata.get("task_assignment_id") or item.metadata.get("task_id") or "") in task_ids
            or item.flow_id.removeprefix("flow.") in {task_id.removeprefix("task.") for task_id in task_ids}
        }
        return {
            "authority": "task_system.project_lifecycle_delete_task_records_preview",
            "selectors": selectors,
            "task_ids": sorted(task_ids),
            "flow_ids": sorted(flow_ids),
            "counts": {
                "task_count": len(task_ids),
                "flow_count": len(flow_ids),
            },
            "preserved": {
                "task_graphs": bool(safeguards.get("preserve_task_graphs", True)),
                "artifacts": bool(safeguards.get("preserve_artifacts", True)),
                "project_instances": bool(safeguards.get("preserve_project_instances", True)),
            },
        }


def _matches_task_selector(payload: dict[str, Any], selectors: dict[str, Any]) -> bool:
    task_id = _payload_text(payload, "task_id")
    task_id_contains = str(selectors.get("task_id_contains") or "").strip()
    task_id_prefix = str(selectors.get("task_id_prefix") or "").strip()
    if task_id_contains and task_id_contains not in task_id:
        return False
    if task_id_prefix and not task_id.startswith(task_id_prefix):
        return False
    environment_id = str(
        payload.get("task_environment_id")
        or dict(payload.get("metadata") or {}).get("task_environment_id")
        or dict(payload.get("metadata") or {}).get("environment_id")
        or dict(payload.get("task_structure") or {}).get("task_environment_id")
        or dict(payload.get("task_policy") or {}).get("task_structure", {}).get("task_environment_id")
        or ""
    ).strip()
    selector_environment = str(selectors.get("task_environment_id") or selectors.get("environment_id") or "").strip()
    if selector_environment and environment_id != selector_environment:
        return False
    domain_id = _payload_text(payload, "domain_id")
    selector_domain = str(selectors.get("domain_id") or "").strip()
    if selector_domain and domain_id != selector_domain:
        return False
    return bool(task_id)


def _payload_text(payload: dict[str, Any], key: str) -> str:
    return str(payload.get(key) or dict(payload.get("metadata") or {}).get(key) or "").strip()


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or "")) or "project"
