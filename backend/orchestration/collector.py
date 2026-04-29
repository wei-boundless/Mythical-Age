from __future__ import annotations

from typing import Any

from .candidates import CandidateEnvelope, CandidateSet


def collect_task_operation_preview_candidates(
    *,
    task_contract: dict[str, Any],
    operation_requirement: dict[str, Any],
    resource_policy: dict[str, Any],
    task_prompt_contract: dict[str, Any],
    prompt_manifest: dict[str, Any],
    topology_preview: dict[str, Any],
    understanding_candidates: tuple[CandidateEnvelope, ...] = (),
    memory_runtime_view: dict[str, Any] | None = None,
    context_policy_preview: dict[str, Any] | None = None,
) -> CandidateSet:
    task_id = str(task_contract.get("task_id") or "task-preview")
    candidates = CandidateSet()
    candidates.add(
        CandidateEnvelope(
            candidate_id=f"candidate:{task_id}:task-contract",
            producer="tasks.contract_builder",
            candidate_type="task_contract",
            payload=_compact_payload(task_contract, ("task_id", "task_family", "task_mode", "source")),
            confidence=1.0,
            reasons=("task contract is the current preview task fact",),
            refs={"task_contract_ref": task_id},
        )
    )
    candidates.add(
        CandidateEnvelope(
            candidate_id=f"candidate:{task_id}:operation-requirement",
            producer="operations.requirement_builder",
            candidate_type="operation_requirement",
            payload=_compact_payload(
                operation_requirement,
                ("requirement_id", "required_operations", "optional_operations", "denied_operations"),
            ),
            confidence=1.0,
            reasons=("operation requirement is candidate-only resource demand",),
            refs={"operation_requirement_ref": str(operation_requirement.get("requirement_id") or "")},
        )
    )
    candidates.add(
        CandidateEnvelope(
            candidate_id=f"candidate:{task_id}:resource-policy-preview",
            producer="operations.policy_builder",
            candidate_type="resource_policy_preview",
            payload=_compact_payload(
                resource_policy,
                (
                    "policy_id",
                    "preview_only",
                    "adopted",
                    "runtime_executable",
                    "allowed_operations",
                    "denied_operations",
                    "requires_approval_operations",
                    "preview_only_operations",
                ),
            ),
            confidence=1.0,
            reasons=("resource policy is preview-only and cannot execute",),
            refs={"resource_policy_ref": str(resource_policy.get("policy_id") or "")},
        )
    )
    candidates.add(
        CandidateEnvelope(
            candidate_id=f"candidate:{task_id}:task-prompt-contract",
            producer="tasks.contract_builder",
            candidate_type="task_prompt_contract",
            payload=_compact_payload(task_prompt_contract, ("contract_id", "task_id", "definition_id", "binding_id")),
            confidence=1.0,
            reasons=("task prompt contract is model-visible preview material",),
            refs={"task_prompt_contract_ref": str(task_prompt_contract.get("contract_id") or "")},
        )
    )
    candidates.add(
        CandidateEnvelope(
            candidate_id=f"candidate:{task_id}:prompt-manifest-preview",
            producer="soul.projection",
            candidate_type="prompt_manifest_preview",
            payload=_compact_payload(prompt_manifest, ("manifest_id", "task_id", "preview_only")),
            confidence=1.0,
            reasons=("prompt manifest is preview-only and cannot carry runtime directives",),
            refs={"prompt_manifest_ref": str(prompt_manifest.get("manifest_id") or "")},
        )
    )
    candidates.add(
        CandidateEnvelope(
            candidate_id=f"candidate:{task_id}:single-agent-topology",
            producer="orchestration.topology",
            candidate_type="execution_topology_preview",
            payload=_compact_payload(
                topology_preview,
                ("topology_id", "task_id", "mode", "preview_only", "adopted", "runtime_executable"),
            ),
            confidence=1.0,
            reasons=("single_agent topology is the only enabled topology in this phase",),
            refs={"execution_topology_ref": str(topology_preview.get("topology_id") or "")},
        )
    )
    candidates.extend(understanding_candidates)
    if memory_runtime_view:
        candidates.add(
            CandidateEnvelope(
                candidate_id=f"candidate:{task_id}:memory-runtime-view",
                producer="memory_system.runtime_view",
                candidate_type="memory_runtime_view",
                payload=_compact_payload(
                    memory_runtime_view,
                    (
                        "view_id",
                        "session_id",
                        "preview_only",
                        "memory_write_allowed",
                        "authority",
                    ),
                ),
                confidence=1.0,
                reasons=("memory runtime view is read-only candidate material",),
                refs={
                    "memory_runtime_view_ref": str(memory_runtime_view.get("view_id") or ""),
                    "context_candidate_count": len(list(memory_runtime_view.get("context_candidates") or [])),
                    "restore_candidate_count": len(list(memory_runtime_view.get("restore_candidates") or [])),
                },
            )
        )
    if context_policy_preview:
        diagnostics = dict(context_policy_preview.get("diagnostics") or {})
        package = dict(context_policy_preview.get("package") or {})
        candidates.add(
            CandidateEnvelope(
                candidate_id=f"candidate:{task_id}:context-policy-preview",
                producer="context_policy.package_builder",
                candidate_type="context_policy_preview",
                payload={
                    "preview_only": context_policy_preview.get("preview_only"),
                    "authority": context_policy_preview.get("authority"),
                    "selected_sections": list(package.get("selected_sections") or []),
                    "rebuild_reason": str(package.get("rebuild_reason") or ""),
                    "memory_write_allowed": diagnostics.get("memory_write_allowed", False),
                },
                confidence=1.0,
                reasons=("context package preview is model-context input, not prompt or decision authority",),
                refs={
                    "memory_runtime_view_ref": str(diagnostics.get("memory_runtime_view_ref") or ""),
                    "context_policy_authority": str(context_policy_preview.get("authority") or ""),
                    "included_candidate_count": int(diagnostics.get("included_candidate_count") or 0),
                },
            )
        )
    return candidates


def _compact_payload(payload: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: payload.get(key) for key in keys if key in payload}
