from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from harness import GraphHarness
from harness.graph.models import safe_id
from harness.runtime import AgentRuntimeServices
from sessions import SessionManager
from task_system.registry.flow_registry import TaskFlowRegistry

from .models import EngagementContract, EngagementEvent, EngagementRunRecord
from .run_repository import EngagementRunRepository


class EngagementDispatcher:
    def __init__(self, backend_dir: Path | str) -> None:
        self.backend_dir = Path(backend_dir)
        self.runs = EngagementRunRepository(self.backend_dir)

    def dispatch(
        self,
        *,
        runtime_host: Any,
        session_id: str,
        turn_id: str,
        contract: EngagementContract,
        agent_profile_ref: str,
    ) -> dict[str, Any]:
        run = EngagementRunRecord(
            engagement_run_id=f"engrun:{uuid.uuid4().hex[:12]}",
            request_id=contract.request_id,
            contract_id=contract.contract_id,
            plan_id=contract.plan_id,
            plan_version=contract.plan_version,
            strategy_kind=contract.execution_strategy.kind,
            status="admitted",
        )
        self.runs.upsert_run(run)
        if hasattr(runtime_host, "runtime_objects"):
            runtime_host.runtime_objects.put_object(
                "engagement_run",
                run.engagement_run_id,
                run.to_dict(),
            )
        self._event(run.engagement_run_id, "admitted", "特定任务合同已通过准入。")
        kind = contract.execution_strategy.kind
        if kind == "graph_task_run":
            return self._dispatch_graph_task_run(
                runtime_host=runtime_host,
                session_id=session_id,
                contract=contract,
                run=run,
            )
        blocked = self.runs.update_run(
            run.engagement_run_id,
            status="blocked",
            closeout={"reason": f"unsupported_strategy:{kind}", "expected_strategy": "graph_task_run"},
        )
        self._event(blocked.engagement_run_id, "blocked", f"执行策略不属于新图任务链路：{kind}。")
        return {
            "decision": "unsupported_strategy",
            "engagement_run": blocked.to_dict(),
            "execution_strategy": kind,
            "closeout": dict(blocked.closeout),
        }

    def _dispatch_graph_task_run(
        self,
        *,
        runtime_host: Any,
        session_id: str,
        contract: EngagementContract,
        run: EngagementRunRecord,
    ) -> dict[str, Any]:
        startup_policy = dict(contract.execution_strategy.startup_policy or {})
        graph_id = str(startup_policy.get("graph_id") or startup_policy.get("task_graph_id") or "").strip()
        registry = TaskFlowRegistry(self.backend_dir)
        graph_config = registry.get_published_graph_harness_config(graph_id)
        if graph_config is None:
            blocked = self.runs.update_run(
                run.engagement_run_id,
                status="blocked",
                closeout={"reason": f"published_graph_harness_config_required:{graph_id}"},
            )
            self._event(blocked.engagement_run_id, "blocked", "图任务缺少已发布运行配置，未启动。")
            return {
                "decision": "blocked",
                "engagement_run": blocked.to_dict(),
                "execution_strategy": contract.execution_strategy.kind,
                "closeout": dict(blocked.closeout),
            }
        graph_harness = _graph_harness_from_runtime_host(runtime_host)
        graph_scope = _engagement_graph_scope(graph_config=graph_config, contract=contract)
        graph_session_manager = SessionManager(self.backend_dir)
        graph_session_id = _create_engagement_graph_session(
            session_manager=graph_session_manager,
            graph_config=graph_config,
            scope=graph_scope,
        )
        try:
            start = graph_harness.start_run(
                session_id=graph_session_id,
                task_id=contract.plan_id,
                graph_config=graph_config,
                initial_inputs={
                    "startup_parameters": dict(contract.startup_parameters or {}),
                    "engagement_contract_ref": contract.contract_id,
                    "engagement_plan_ref": contract.plan_id,
                    "engagement_run_ref": run.engagement_run_id,
                    "runtime_scope": graph_scope,
                },
                diagnostics={
                    "source": "task_system.engagement.graph_task_run",
                    "launch_session_id": str(session_id or ""),
                    "graph_root_session_id": graph_session_id,
                    "session_scope": graph_scope,
                    "session_scope_key": _scope_key(graph_scope),
                    "workspace_view": str(graph_scope.get("workspace_view") or ""),
                    "task_environment_id": str(graph_scope.get("task_environment_id") or ""),
                    "project_id": str(graph_scope.get("project_id") or ""),
                    "runtime_scope": graph_scope,
                    "engagement_contract_ref": contract.contract_id,
                    "engagement_plan_ref": contract.plan_id,
                    "engagement_run_ref": run.engagement_run_id,
                },
                dispatch_ready=bool(startup_policy.get("dispatch_ready", True)),
            )
            graph_session_manager.bind_session_graph_instance(
                graph_session_id,
                graph_run_id=start.graph_run.graph_run_id,
                task_run_id=start.task_run.task_run_id,
                graph_id=graph_config.graph_id,
                graph_harness_config_id=graph_config.config_id,
                session_scope=graph_scope,
                task_environment_id=str(graph_scope.get("task_environment_id") or ""),
                project_id=str(graph_scope.get("project_id") or ""),
            )
        except Exception:
            graph_session_manager.delete_session(graph_session_id)
            raise
        updated = self.runs.update_run(
            run.engagement_run_id,
            status="running",
            task_run_id=start.task_run.task_run_id,
            workflow_run_id=start.graph_run.graph_run_id,
            closeout={
                "graph_id": graph_config.graph_id,
                "graph_run_id": start.graph_run.graph_run_id,
                "graph_harness_config_id": graph_config.config_id,
            },
        )
        if hasattr(runtime_host, "runtime_objects"):
            runtime_host.runtime_objects.put_object(
                "engagement_run",
                updated.engagement_run_id,
                updated.to_dict(),
            )
        self._event(updated.engagement_run_id, "dispatched", "特定任务已进入图任务运行链路。")
        return {
            "decision": "started",
            "engagement_run": updated.to_dict(),
            "execution_strategy": contract.execution_strategy.kind,
            "task_run": start.task_run.to_dict(),
            "graph_run": start.graph_run.to_dict(),
            "graph_loop_state": start.loop_state.to_dict(),
            "graph_harness_config": graph_config.to_dict(),
            "node_work_orders": [item.to_dict() for item in tuple(start.node_work_orders or ())],
            "events": [dict(item) for item in tuple(start.events or ())],
        }

    def _event(self, engagement_run_id: str, event_type: str, summary: str) -> None:
        self.runs.append_event(
            EngagementEvent(
                engagement_run_id=engagement_run_id,
                event_type=event_type,
                summary=summary,
                created_at=str(time.time()),
            )
        )


def _graph_harness_from_runtime_host(runtime_host: Any) -> GraphHarness:
    graph_harness = getattr(runtime_host, "graph_harness", None)
    if graph_harness is not None:
        return graph_harness
    return GraphHarness(
        services=AgentRuntimeServices.from_runtime_host(runtime_host),
    )


def _engagement_graph_scope(*, graph_config: Any, contract: EngagementContract) -> dict[str, str]:
    binding = _graph_binding_contract(graph_config)
    task_environment_id = str(
        binding.get("task_environment_id")
        or getattr(graph_config, "task_environment_id", "")
        or contract.task_environment_id
        or ""
    ).strip()
    startup_parameters = dict(contract.startup_parameters or {})
    project_id = str(
        binding.get("project_id")
        or startup_parameters.get("project_id")
        or startup_parameters.get("workspace_project_id")
        or ""
    ).strip()
    workspace_view = str(binding.get("workspace_view") or ("project" if project_id else "task_environment")).strip()
    return {
        "workspace_view": workspace_view or ("project" if project_id else "task_environment"),
        "task_environment_id": task_environment_id,
        "project_id": project_id,
        "scope_source": "task_system.engagement.graph_binding_contract",
    }


def _graph_binding_contract(graph_config: Any) -> dict[str, Any]:
    contracts = dict(getattr(graph_config, "contracts", {}) or {})
    environment = dict(getattr(graph_config, "environment", {}) or {})
    control = dict(getattr(graph_config, "control", {}) or {})
    return dict(
        contracts.get("graph_binding_contract")
        or control.get("graph_binding")
        or environment.get("graph_binding")
        or {}
    )


def _create_engagement_graph_session(
    *,
    session_manager: SessionManager,
    graph_config: Any,
    scope: dict[str, str],
) -> str:
    graph_id = str(getattr(graph_config, "graph_id", "") or "graph")
    session_id = f"graph-session-{safe_id(graph_id)}-{uuid.uuid4().hex[:12]}"
    title = str(getattr(graph_config, "graph_title", "") or graph_id)
    session_manager.create_session(
        session_id=session_id,
        title=f"Graph run - {title}",
        scope={
            "workspace_view": str(scope.get("workspace_view") or ""),
            "task_environment_id": str(scope.get("task_environment_id") or ""),
            "project_id": str(scope.get("project_id") or ""),
        },
    )
    return session_id


def _scope_key(scope: dict[str, Any]) -> str:
    return "|".join(
        [
            str(scope.get("workspace_view") or "").strip(),
            str(scope.get("task_environment_id") or "").strip(),
            str(scope.get("project_id") or "").strip(),
        ]
    )
