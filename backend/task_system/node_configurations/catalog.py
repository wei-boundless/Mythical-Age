from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import TaskNodeConfigurationSpec
from .repository import TaskNodeConfigurationRepository


def build_node_configuration_catalog(
    base_dir: Path,
    *,
    task_graphs: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    agents: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    profiles: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    contract_ids: set[str] | None = None,
) -> dict[str, Any]:
    repository = TaskNodeConfigurationRepository(base_dir)
    stored = {item.node_config_id: item for item in repository.list()}
    derived = {
        item.node_config_id: item
        for item in _derive_node_configurations(task_graphs)
        if item.node_config_id not in stored
    }
    specs = [*stored.values(), *derived.values()]
    usage = _build_usage_index(specs, task_graphs)
    issues = _build_issues(
        specs,
        agents={str(item.get("agent_id") or item.get("id") or "") for item in agents},
        profiles={str(item.get("agent_profile_id") or "") for item in profiles},
        contract_ids=contract_ids or set(),
    )
    return {
        "authority": "task_system.node_configuration_catalog",
        "node_configurations": [item.to_dict() for item in sorted(specs, key=lambda item: item.node_config_id)],
        "usage_index": usage,
        "issues": issues,
        "summary": {
            "node_configuration_count": len(specs),
            "stored_node_configuration_count": len(stored),
            "migration_candidate_count": len(derived),
            "issue_count": len(issues),
        },
    }


def _derive_node_configurations(task_graphs: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[TaskNodeConfigurationSpec]:
    specs: list[TaskNodeConfigurationSpec] = []
    for graph in task_graphs:
        graph_id = str(graph.get("graph_id") or "").strip()
        graph_environment_id = _graph_environment_id(graph)
        for node in list(graph.get("nodes") or []):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("node_id") or "").strip()
            if not graph_id or not node_id:
                continue
            metadata = dict(node.get("metadata") or {})
            existing_id = str(node.get("node_config_id") or metadata.get("node_config_id") or "").strip()
            node_config_id = existing_id or f"nodecfg.{_slug(graph_id)}.{_slug(node_id)}"
            executor_ref = {
                "agent_id": str(node.get("agent_id") or metadata.get("agent_id") or "").strip(),
                "agent_profile_id": str(metadata.get("agent_profile_id") or dict(node.get("executor_policy") or {}).get("agent_profile_id") or "").strip(),
                "agent_selection_policy": str(node.get("agent_selection_policy") or "explicit_agent").strip(),
            }
            prompt_contract = dict(metadata.get("prompt_contract") or {}) if isinstance(metadata.get("prompt_contract"), dict) else {}
            role_prompt = str(prompt_contract.get("role_prompt") or metadata.get("role_prompt") or metadata.get("prompt") or "").strip()
            specs.append(
                TaskNodeConfigurationSpec(
                    node_config_id=node_config_id,
                    title=str(node.get("title") or node_id),
                    description=str(metadata.get("description") or ""),
                    node_kind=str(node.get("node_type") or "agent"),
                    environment_scope=(graph_environment_id,) if graph_environment_id else (),
                    role_prompt=role_prompt,
                    executor_ref={key: value for key, value in executor_ref.items() if value},
                    contract_bindings={
                        "input_contract_id": str(node.get("input_contract_id") or "").strip(),
                        "output_contract_id": str(node.get("output_contract_id") or "").strip(),
                        "node_contract_id": str(node.get("node_contract_id") or node.get("contract_id") or "").strip(),
                        **dict(node.get("contract_bindings") or {}),
                    },
                    model_requirements=dict(metadata.get("model_requirements") or {}),
                    tool_policy=dict(node.get("executor_policy") or {}),
                    memory_policy={
                        "read": dict(node.get("memory_read_policy") or {}),
                        "writeback": dict(node.get("memory_writeback_policy") or {}),
                        "dynamic_read": dict(node.get("dynamic_memory_read_policy") or {}),
                    },
                    artifact_policy=dict(node.get("artifact_policy") or {}),
                    failure_policy=dict(node.get("failure_policy") or {}),
                    human_gate_policy=dict(node.get("human_gate_policy") or {}),
                    metadata={
                        "migration_source": "task_graph_node",
                        "source_graph_id": graph_id,
                        "source_node_id": node_id,
                        "requires_review": not existing_id,
                    },
                )
            )
    return specs


def _build_usage_index(
    specs: list[TaskNodeConfigurationSpec],
    task_graphs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, list[dict[str, str]]]:
    known = {item.node_config_id for item in specs}
    usage: dict[str, list[dict[str, str]]] = {item: [] for item in known}
    for graph in task_graphs:
        graph_id = str(graph.get("graph_id") or "").strip()
        for node in list(graph.get("nodes") or []):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("node_id") or "").strip()
            node_config_id = str(node.get("node_config_id") or dict(node.get("metadata") or {}).get("node_config_id") or "").strip()
            if not node_config_id and graph_id and node_id:
                node_config_id = f"nodecfg.{_slug(graph_id)}.{_slug(node_id)}"
            if node_config_id in usage:
                usage[node_config_id].append({"graph_id": graph_id, "node_id": node_id})
    return usage


def _build_issues(
    specs: list[TaskNodeConfigurationSpec],
    *,
    agents: set[str],
    profiles: set[str],
    contract_ids: set[str],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for spec in specs:
        agent_id = str(spec.executor_ref.get("agent_id") or "").strip()
        profile_id = str(spec.executor_ref.get("agent_profile_id") or "").strip()
        if not agent_id:
            issues.append(_issue(spec, "agent_missing", "节点配置缺少 agent_id。", "warning"))
        elif agents and agent_id not in agents:
            issues.append(_issue(spec, "agent_not_found", f"节点配置引用的 agent 不存在：{agent_id}", "error"))
        if profile_id and profiles and profile_id not in profiles:
            issues.append(_issue(spec, "runtime_profile_not_found", f"节点配置引用的运行档案不存在：{profile_id}", "error"))
        for key in ("input_contract_id", "output_contract_id", "node_contract_id"):
            contract_id = str(spec.contract_bindings.get(key) or "").strip()
            if contract_id and contract_ids and contract_id not in contract_ids:
                issues.append(_issue(spec, "contract_not_found", f"{key} 引用的契约不存在：{contract_id}", "error"))
    return issues


def _issue(spec: TaskNodeConfigurationSpec, code: str, message: str, severity: str) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "severity": severity,
        "node_config_id": spec.node_config_id,
        "authority": "task_system.node_configuration_issue",
    }


def _graph_environment_id(graph: dict[str, Any]) -> str:
    runtime_policy = dict(graph.get("runtime_policy") or {})
    context_policy = dict(graph.get("context_policy") or {})
    metadata = dict(graph.get("metadata") or {})
    return str(
        runtime_policy.get("task_environment_id")
        or runtime_policy.get("environment_id")
        or context_policy.get("task_environment_id")
        or context_policy.get("environment_id")
        or metadata.get("task_environment_id")
        or metadata.get("environment_id")
        or ""
    ).strip()


def _slug(value: str) -> str:
    return ".".join(part for part in str(value or "").replace(":", ".").replace("_", ".").replace("-", ".").split(".") if part)
