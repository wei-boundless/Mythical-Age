from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from task_system.contracts.contracts import TaskContract
from task_system.environments import (
    TaskEnvironmentRegistry,
    default_task_environment_registry,
    task_environment_registry_from_backend_dir,
)
from task_system.registry.flow_models import SpecificTaskRecord, TaskExecutionPolicy
from task_system.tasks import resolve_specific_task_assembly_policy


@dataclass(frozen=True, slots=True)
class TaskContractIssuer:
    """Issues fixed task contracts from configured SpecificTask records."""

    authority: str = "task_system.task_contract_issuer"
    backend_dir: Path | None = None
    environment_registry: TaskEnvironmentRegistry | None = None

    def issue_specific_task_contract(
        self,
        *,
        session_id: str,
        task_record: SpecificTaskRecord | dict[str, Any],
        objective: str = "",
        source: str = "task_library",
        source_ref: str = "",
        environment_id: str = "",
        flow_contract_binding: dict[str, Any] | None = None,
        execution_policy: TaskExecutionPolicy | dict[str, Any] | None = None,
        startup_parameters: dict[str, Any] | None = None,
    ) -> TaskContract:
        record = _specific_task_record(task_record)
        execution = _task_execution_policy(execution_policy)
        startup = dict(startup_parameters or {})
        environment_registry = self.environment_registry or (
            task_environment_registry_from_backend_dir(self.backend_dir) if self.backend_dir is not None else default_task_environment_registry()
        )
        startup_contract = {
            **startup,
            **({"environment_id": environment_id} if environment_id else {}),
        }
        policy = resolve_specific_task_assembly_policy(
            task_record=record,
            execution_policy=execution,
            runtime_contract=startup_contract,
            environment_registry=environment_registry,
        )
        environment = environment_registry.require(policy.environment_id)
        flow_binding = dict(flow_contract_binding or {})
        task_policy = dict(record.task_policy or {})
        metadata = dict(record.metadata or {})
        goal = str(objective or startup.get("objective") or record.description or record.task_title).strip()
        graph_ref = str(
            startup.get("graph_ref")
            or startup.get("graph_id")
            or task_policy.get("graph_ref")
            or task_policy.get("graph_id")
            or metadata.get("graph_ref")
            or metadata.get("graph_id")
            or ""
        ).strip()
        runtime_shape = policy.runtime_shape
        graph_contract = {
            "graph_ref": graph_ref,
            "graph_harness_config_ref": str(
                startup.get("graph_harness_config_ref")
                or startup.get("graph_harness_config_id")
                or task_policy.get("graph_harness_config_ref")
                or task_policy.get("graph_harness_config_id")
                or metadata.get("graph_harness_config_ref")
                or metadata.get("graph_harness_config_id")
                or ""
            ).strip(),
            "graph_policy": dict(task_policy.get("graph_policy") or metadata.get("graph_policy") or {}),
        } if runtime_shape == "task_graph" or graph_ref else {}
        return TaskContract(
            contract_id=f"taskcontract:{uuid.uuid4().hex[:12]}",
            contract_kind="specific_task",
            session_id=session_id,
            task_id=str(record.task_id or ""),
            task_spec_ref=str(record.task_id or ""),
            environment_id=environment.record.environment_id,
            source=source,
            source_ref=source_ref or f"task_system.specific_task:{record.task_id}",
            objective=goal,
            user_goal=goal,
            runtime_shape=runtime_shape,
            runtime_requirements={
                "runtime_shape": runtime_shape,
                "environment_id": environment.record.environment_id,
                "tool_capability_requirements": policy.tool_capability_requirements.to_dict(),
                "resource_requirements": dict(policy.resource_requirements),
                "memory_requirements": dict(policy.memory_requirements),
            },
            loop_requirements={
                "loop": dict(task_policy.get("loop") or metadata.get("loop") or {}),
                "flow_ref": policy.flow_ref,
            },
            runtime_assembly_plan={
                "kind": "runtime_assembly_request",
                "schema_version": "runtime_assembly_plan.request.v1",
                "environment_id": environment.record.environment_id,
                "runtime_shape": runtime_shape,
                "agent_selection": policy.agent_selection.to_dict(),
                "extension_slots": dict(task_policy.get("runtime_assembly_extension_slots") or {}),
            },
            loop_plan={
                "kind": "loop_request",
                "schema_version": "loop_plan.request.v1",
                "runtime_shape": runtime_shape,
                "flow_ref": policy.flow_ref,
                "extension_slots": dict(task_policy.get("loop_extension_slots") or {}),
            },
            graph_contract=graph_contract,
            graph_runtime_assembly_plan={
                "kind": "graph_harness_config_request",
                "schema_version": "graph_harness_config_request.v1",
                "graph_ref": graph_ref,
                "graph_harness_config_ref": str(graph_contract.get("graph_harness_config_ref") or ""),
                "environment_id": environment.record.environment_id,
                "extension_slots": dict(task_policy.get("graph_runtime_assembly_extension_slots") or {}),
            } if graph_contract else {},
            graph_loop_plan={
                "kind": "graph_loop_request",
                "schema_version": "graph_loop_plan.request.v1",
                "graph_ref": graph_ref,
                "graph_harness_config_ref": str(graph_contract.get("graph_harness_config_ref") or ""),
                "extension_slots": dict(task_policy.get("graph_loop_extension_slots") or {}),
            } if graph_contract else {},
            human_gate_contract=dict(task_policy.get("human_gate_policy") or metadata.get("human_gate_policy") or {}),
            working_objects=(
                {"kind": "specific_task", "ref": str(record.task_id or "")},
            ),
            input_refs=(
                {"kind": "task_record", "ref": str(record.task_id or "")},
            ),
            resource_scope=dict(policy.resource_requirements),
            tool_scope=policy.tool_capability_requirements.to_dict(),
            memory_scope=dict(policy.memory_requirements),
            artifact_scope=dict(task_policy.get("artifact_policy") or {}),
            agent_assignment=policy.agent_selection.to_dict(),
            prompt_pack_refs=policy.prompt_requirements.required_refs,
            skill_pack_refs=policy.skill_requirements.required_refs,
            output_contract={
                "contract_id": policy.output_contract_ref,
                "flow_contract_binding": flow_binding,
            },
            acceptance_policy=dict(policy.acceptance_policy),
            recovery_policy=dict(task_policy.get("recovery_policy") or metadata.get("recovery_policy") or {}),
            approval_policy=dict(task_policy.get("approval_policy") or metadata.get("approval_policy") or {}),
            risk_policy=dict(task_policy.get("risk_policy") or metadata.get("risk_policy") or {}),
            extension_slots={
                "runtime_contract_hints": dict(task_policy.get("runtime_contract_hints") or {}),
                "harness_contract_hints": dict(task_policy.get("harness_contract_hints") or {}),
                **dict(metadata.get("contract_extension_slots") or {}),
            },
            status="issued",
            metadata={
                "created_by": self.authority,
                "created_at": time.time(),
                "task_title": record.task_title,
                "environment_spec_id": environment.spec.spec_id,
            },
        )


def _specific_task_record(payload: SpecificTaskRecord | dict[str, Any]) -> SpecificTaskRecord:
    if isinstance(payload, SpecificTaskRecord):
        return payload
    data = dict(payload or {})
    metadata = dict(data.get("metadata") or {})
    for key in ("environment_id", "task_environment_id", "graph_id", "graph_ref"):
        if str(data.get(key) or "").strip() and not str(metadata.get(key) or "").strip():
            metadata[key] = data[key]
    if metadata:
        data["metadata"] = metadata
    allowed = set(SpecificTaskRecord.__dataclass_fields__.keys())
    return SpecificTaskRecord(**{key: value for key, value in data.items() if key in allowed})


def _task_execution_policy(payload: TaskExecutionPolicy | dict[str, Any] | None) -> TaskExecutionPolicy | None:
    if payload is None or isinstance(payload, TaskExecutionPolicy):
        return payload
    data = dict(payload or {})
    allowed = set(TaskExecutionPolicy.__dataclass_fields__.keys())
    if not str(data.get("policy_id") or "").strip() or not str(data.get("task_id") or "").strip():
        return None
    data.setdefault("execution_mode", "single_agent")
    return TaskExecutionPolicy(**{key: value for key, value in data.items() if key in allowed})


