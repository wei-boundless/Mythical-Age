from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from soul.projection_instances import ProjectionInstanceRegistry
from tasks.flow_registry import TaskFlowRegistry

from .models import HealthAgentRun, HealthIssue, ProblemNode


def default_health_issues(now: float | None = None) -> tuple[HealthIssue, ...]:
    timestamp = time.time() if now is None else now
    return (
        HealthIssue(
            issue_id="health:issue:sample-task-system-chain",
            title="任务系统链路权限样例问题",
            owner_system="task_system",
            severity="medium",
            status="triage_ready",
            source="system_bootstrap",
            conversation_ref="sample:conversation:task-system",
            runtime_trace_refs=("runtime-loop:sample",),
            prompt_manifest_refs=("prompt-manifest:sample",),
            memory_refs=("memory-runtime-view:sample",),
            assertion_refs=("assertion:sample",),
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"sample": True},
        ),
    )


def default_problem_nodes() -> tuple[ProblemNode, ...]:
    return (
        ProblemNode(
            node_id="problem-node:sample:task-binding",
            issue_id="health:issue:sample-task-system-chain",
            system="task_system",
            stage="TaskAgentBinding",
            evidence_refs=("binding:flow.health.issue_triage:agent:health:maintainer",),
            diagnosis="样例节点：用于验证任务系统能展示绑定、权限和投影链路。",
            confidence=0.8,
            suggested_action="检查 AgentCapabilityProfile 与任务流绑定是否一致。",
        ),
    )


def default_health_agent_runs(now: float | None = None) -> tuple[HealthAgentRun, ...]:
    timestamp = time.time() if now is None else now
    return (
        HealthAgentRun(
            run_id="health-run:sample:issue-triage",
            issue_id="health:issue:sample-task-system-chain",
            task_run_id="taskrun:sample:health-issue-triage",
            agent_id="agent:health:maintainer",
            agent_profile_id="health_maintainer_agent",
            runtime_lane="health_issue_read",
            task_mode="issue_triage",
            workflow_id="workflow.health.issue_triage",
            projection_id="projection:xuannv__health_maintainer:sample",
            prompt_manifest_id="prompt-manifest:projection:xuannv__health_maintainer:sample",
            status="sample",
            terminal_reason="not_executed_sample",
            result_ref="HealthTriageResult:sample",
            created_at=timestamp,
            metadata={"sample": True},
        ),
    )


class HealthRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def list_issues(self) -> list[HealthIssue]:
        return list(default_health_issues())

    def list_agent_runs(self) -> list[HealthAgentRun]:
        return list(default_health_agent_runs())

    def list_problem_nodes(self) -> list[ProblemNode]:
        return list(default_problem_nodes())

    def build_overview(self) -> dict[str, Any]:
        issues = self.list_issues()
        runs = self.list_agent_runs()
        problem_nodes = self.list_problem_nodes()
        return {
            "authority": "health_system.registry",
            "summary": {
                "issue_count": len(issues),
                "open_issue_count": sum(1 for item in issues if item.status not in {"resolved", "closed"}),
                "agent_run_count": len(runs),
                "problem_node_count": len(problem_nodes),
            },
            "issues": [item.to_dict() for item in issues],
            "agent_runs": [item.to_dict() for item in runs],
            "problem_nodes": [item.to_dict() for item in problem_nodes],
        }

    def preview_agent_run(self, *, issue_id: str, task_mode: str = "issue_triage") -> dict[str, Any]:
        issue = next((item for item in self.list_issues() if item.issue_id == issue_id), None)
        if issue is None:
            raise KeyError(issue_id)
        task_registry = TaskFlowRegistry(self.base_dir)
        flow = next((item for item in task_registry.list_flows() if item.task_mode == task_mode), None)
        if flow is None:
            raise KeyError(task_mode)
        binding = task_registry.build_binding_for_flow(flow)
        if binding.validation_state != "valid":
            return {
                "authority": "health_system.agent_run_preview",
                "status": "blocked",
                "issue": issue.to_dict(),
                "flow": flow.to_dict(),
                "binding": binding.to_dict(),
                "reason": "task agent binding is invalid",
            }
        projection = ProjectionInstanceRegistry(self.base_dir).preview_instance(
            template_id=binding.projection_template_id,
            task_id=f"task.health.{task_mode}:{issue.issue_id}",
            agent_id=binding.agent_id,
            runtime_lane=binding.runtime_lane,
            resource_policy_ref=binding.resource_policy_ref,
        )
        return {
            "authority": "health_system.agent_run_preview",
            "status": "ready",
            "issue": issue.to_dict(),
            "flow": flow.to_dict(),
            "binding": binding.to_dict(),
            "projection_instance": projection.to_dict(),
            "runtime_directive_lane": {
                "lane_id": f"lane:{binding.runtime_lane}:{issue.issue_id}",
                "lane_type": binding.runtime_lane,
                "agent_id": binding.agent_id,
                "agent_profile_id": binding.agent_profile_id,
                "task_id": f"task.health.{task_mode}:{issue.issue_id}",
                "memory_scope": binding.memory_scope,
                "output_contract_id": binding.output_contract_id,
            },
        }
