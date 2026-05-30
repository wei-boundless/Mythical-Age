from __future__ import annotations

from typing import Any

from .models import GraphHarnessConfig, GraphNodeWorkOrder


class OutputPolicyResolver:
    """Resolve graph node output contracts before artifact post-processing."""

    authority = "harness.graph.output_policy_resolver"

    def resolve(
        self,
        *,
        graph_config: GraphHarnessConfig,
        work_order: GraphNodeWorkOrder,
    ) -> dict[str, Any]:
        graph_slot = dict(work_order.graph_slot or {})
        slot_output = dict(graph_slot.get("output_contract") or {})
        expected = dict(work_order.expected_result_contract or {})
        bindings = dict(expected.get("contract_bindings") or {})
        output_binding = dict(bindings.get("output") or {})
        artifact_binding = dict(bindings.get("artifact") or {})
        node_artifact_policy = dict(work_order.artifact_view_request.get("node_artifact_policy") or {})
        output_policy = _merge_dicts(
            _legacy_artifact_output_policy(artifact_binding=artifact_binding, node_artifact_policy=node_artifact_policy),
            dict(slot_output.get("output_policy") or {}),
            output_binding,
        )
        artifact_materialization = dict(output_policy.get("artifact_materialization_policy") or {})
        artifact_repository = _artifact_repository_policy(
            output_policy=output_policy,
            artifact_materialization=artifact_materialization,
            graph_config=graph_config,
            work_order=work_order,
        )
        artifact_targets = _artifact_targets(
            slot_output=slot_output,
            output_policy=output_policy,
            artifact_materialization=artifact_materialization,
            artifact_binding=artifact_binding,
            node_artifact_policy=node_artifact_policy,
        )
        environment_projection = _environment_projection(graph_config)
        no_artifact_output = False if artifact_targets else bool(output_policy.get("no_artifact_output") is True or output_policy.get("artifact_output") is False)
        return {
            "output_contract_id": str(
                output_policy.get("output_contract_id")
                or expected.get("output_contract_id")
                or expected.get("node_contract_id")
                or ""
            ),
            "output_kind": str(output_policy.get("output_kind") or output_policy.get("kind") or ""),
            "primary_content_key": str(output_policy.get("primary_content_key") or artifact_materialization.get("primary_content_key") or "final_answer"),
            "output_policy": output_policy,
            "artifact_targets": artifact_targets,
            "artifact_materialization_policy": {
                **artifact_materialization,
                "required": bool(artifact_materialization.get("required") or any(bool(item.get("required")) for item in artifact_targets)),
                "artifact_targets": artifact_targets,
            },
            "artifact_repository_policy": artifact_repository,
            "environment_projection": environment_projection,
            "no_artifact_output": no_artifact_output,
            "source_authority": "graph_slot.output_contract",
            "authority": self.authority,
        }


def resolve_output_policy(*, graph_config: GraphHarnessConfig, work_order: GraphNodeWorkOrder) -> dict[str, Any]:
    return OutputPolicyResolver().resolve(graph_config=graph_config, work_order=work_order)


def _legacy_artifact_output_policy(*, artifact_binding: dict[str, Any], node_artifact_policy: dict[str, Any]) -> dict[str, Any]:
    artifact_policy = dict(artifact_binding.get("artifact_policy") or artifact_binding or node_artifact_policy or {})
    targets = _dict_list(artifact_policy.get("artifacts") or artifact_policy.get("artifact_targets"))
    if not artifact_policy and not targets:
        return {"no_artifact_output": True, "authority": "harness.graph.output_policy.no_artifact_output"}
    return {
        "primary_content_key": str(artifact_policy.get("primary_content_key") or "final_answer"),
        "artifact_materialization_policy": {
            "required": bool(artifact_policy.get("required") or any(bool(item.get("required")) for item in targets)),
            "artifact_targets": targets,
            "artifact_root": str(artifact_policy.get("artifact_root") or ""),
            "default_artifact_root": str(artifact_policy.get("default_artifact_root") or ""),
            "subdir_template": str(artifact_policy.get("subdir_template") or artifact_policy.get("scope_template") or ""),
            "path_template_source": "artifact_policy",
            "authority": "harness.graph.output_policy.compiled_from_artifact_policy",
        },
        "artifact_repository_policy": {
            "target_repository_id": str(artifact_policy.get("target_repository_id") or artifact_policy.get("repository_id") or ""),
            "target_collection_id": str(artifact_policy.get("target_collection_id") or artifact_policy.get("collection_id") or ""),
            "lifecycle_policy": dict(artifact_policy.get("lifecycle_policy") or {}),
        },
        "authority": "harness.graph.output_policy.compiled_from_artifact_policy",
    }


def _artifact_targets(
    *,
    slot_output: dict[str, Any],
    output_policy: dict[str, Any],
    artifact_materialization: dict[str, Any],
    artifact_binding: dict[str, Any],
    node_artifact_policy: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = [
        slot_output.get("artifact_targets"),
        artifact_materialization.get("artifact_targets"),
        output_policy.get("artifact_targets"),
        artifact_binding.get("artifact_targets"),
        dict(artifact_binding.get("artifact_policy") or {}).get("artifact_targets"),
        dict(artifact_binding.get("artifact_policy") or {}).get("artifacts"),
        node_artifact_policy.get("artifact_targets"),
        node_artifact_policy.get("artifacts"),
    ]
    for value in candidates:
        targets = _dict_list(value)
        if targets:
            primary_key = str(output_policy.get("primary_content_key") or artifact_materialization.get("primary_content_key") or "final_answer")
            return [
                {
                    **dict(item),
                    "content_source": str(item.get("content_source") or primary_key or "final_answer"),
                    "authority": str(item.get("authority") or "harness.graph.resolved_output_artifact_target"),
                }
                for item in targets
            ]
    return []


def _artifact_repository_policy(
    *,
    output_policy: dict[str, Any],
    artifact_materialization: dict[str, Any],
    graph_config: GraphHarnessConfig,
    work_order: GraphNodeWorkOrder,
) -> dict[str, Any]:
    environment_policy = dict(dict(graph_config.environment or {}).get("artifact_policy") or {})
    materialization_repo = dict(artifact_materialization.get("artifact_repository_policy") or {})
    output_repo = dict(output_policy.get("artifact_repository_policy") or {})
    node_policy = dict(work_order.artifact_view_request.get("node_artifact_policy") or {})
    return {
        "repository_id": str(
            output_repo.get("target_repository_id")
            or output_repo.get("repository_id")
            or materialization_repo.get("target_repository_id")
            or artifact_materialization.get("target_repository_id")
            or node_policy.get("target_repository_id")
            or node_policy.get("repository_id")
            or environment_policy.get("artifact_repository_id")
            or environment_policy.get("artifact_root")
            or "artifact.repository.default"
        ),
        "collection_id": str(
            output_repo.get("target_collection_id")
            or output_repo.get("collection_id")
            or materialization_repo.get("target_collection_id")
            or artifact_materialization.get("target_collection_id")
            or node_policy.get("target_collection_id")
            or node_policy.get("collection_id")
            or "default"
        ),
        "lifecycle_policy": dict(
            output_repo.get("lifecycle_policy")
            or materialization_repo.get("lifecycle_policy")
            or artifact_materialization.get("lifecycle_policy")
            or node_policy.get("lifecycle_policy")
            or {}
        ),
        "authority": "harness.graph.resolved_artifact_repository_policy",
    }


def _environment_projection(graph_config: GraphHarnessConfig) -> dict[str, Any]:
    environment = dict(graph_config.environment or {})
    storage = dict(environment.get("storage_space") or {})
    artifact_policy = dict(environment.get("artifact_policy") or {})
    return {
        "task_environment_id": str(graph_config.task_environment_id or environment.get("environment_id") or ""),
        "environment_artifact_root": str(storage.get("artifact_root") or ""),
        "environment_storage_root": str(storage.get("environment_storage_root") or ""),
        "environment_artifact_repository": str(artifact_policy.get("artifact_root") or artifact_policy.get("artifact_repository_id") or ""),
        "authority": "harness.graph.output_environment_projection",
    }


def _merge_dicts(*payloads: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for payload in payloads:
        for key, value in dict(payload or {}).items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = _merge_dicts(dict(result[key]), value)
            elif value not in ("", None, [], {}):
                result[key] = value
    return result


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [dict(value)]
    return [dict(item) for item in list(value or []) if isinstance(item, dict)]
