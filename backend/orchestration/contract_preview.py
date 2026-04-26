from __future__ import annotations

from typing import Any

from orchestration.behavior_models import ContractPreview
from tools.contracts import ToolContractDecision, ToolContractGate, ToolScope


def build_contract_previews(
    *,
    runtime: Any,
    execution: Any,
) -> list[dict[str, Any]]:
    dispatch_plan = getattr(execution, "dispatch_plan", None)
    tool_names = _candidate_tool_names(execution)
    selected_tool = str(getattr(getattr(execution, "query_understanding", None), "tool_name", "") or "").strip()
    if selected_tool and selected_tool not in tool_names:
        tool_names.insert(0, selected_tool)

    previews: list[dict[str, Any]] = []
    for tool_name in tool_names:
        previews.append(
            _preview_tool(
                runtime=runtime,
                execution=execution,
                tool_name=tool_name,
                dispatch_plan=dispatch_plan,
            ).to_dict()
        )
    return previews


def _preview_tool(
    *,
    runtime: Any,
    execution: Any,
    tool_name: str,
    dispatch_plan: Any,
) -> ContractPreview:
    query_runtime = getattr(runtime, "query_runtime", runtime)
    tool_runtime = runtime.tool_runtime
    permission_service = runtime.permission_service
    query_understanding = getattr(execution, "query_understanding", None)
    tool_input = dict(
        getattr(execution, "tool_input", None)
        or getattr(query_understanding, "tool_input", None)
        or {"query": getattr(execution, "message", "")}
    )
    definition = tool_runtime.get_definition(tool_name)
    contract = tool_runtime.get_contract(tool_name)
    mode = query_runtime._effective_tool_contract_mode(tool_name)
    scope = _tool_scope(execution, dispatch_plan)
    if contract is None:
        contract_decision = ToolContractDecision(
            tool_name=tool_name,
            mode=mode,
            action="deny",
            reason="missing_tool_contract",
        )
    else:
        contract_decision = ToolContractGate(mode=mode).evaluate(
            tool_name=tool_name,
            contract=contract,
            tool_input=tool_input,
            tool_scope=scope,
            binding_context=_binding_context(execution, tool_input),
        )

    permission_decision = permission_service.can_invoke_tool(
        tool_name,
        allowed_tools=scope,
        direct_route=True,
        tool_input=tool_input,
    )
    return ContractPreview(
        tool_name=tool_name,
        scope_allowed=scope.allows(tool_name),
        contract_action=contract_decision.action,
        contract_reason=contract_decision.reason,
        permission_allowed=permission_decision.allowed,
        permission_reason=permission_decision.reason,
        missing_inputs=list(contract_decision.missing_inputs),
        missing_bindings=list(contract_decision.missing_bindings),
        risk_tags=list(getattr(permission_decision, "risk_tags", []) or getattr(definition, "safety_tags", []) or []),
    )


def _candidate_tool_names(execution: Any) -> list[str]:
    names: list[str] = []
    dispatch_plan = getattr(execution, "dispatch_plan", None)
    for candidate in list(getattr(dispatch_plan, "tool_candidates", []) or []):
        name = str(getattr(candidate, "name", "") or "").strip()
        if name and name not in names:
            names.append(name)
    understanding = getattr(execution, "query_understanding", None)
    for name in list(getattr(understanding, "candidate_tools", []) or []):
        normalized = str(name or "").strip()
        if normalized and normalized not in names:
            names.append(normalized)
    return names


def _tool_scope(execution: Any, dispatch_plan: Any) -> ToolScope:
    scope = getattr(dispatch_plan, "effective_tool_scope", None)
    if isinstance(scope, ToolScope):
        return scope
    active_skill = getattr(execution, "active_skill", None)
    if active_skill is not None and hasattr(active_skill, "tool_scope"):
        return active_skill.tool_scope()
    return ToolScope(source="skill", reason="no_active_skill")


def _binding_context(execution: Any, tool_input: dict[str, Any]) -> dict[str, Any]:
    structured_binding = getattr(execution, "structured_binding", None)
    return {
        "active_dataset": (
            structured_binding.dataset_path
            if structured_binding is not None and getattr(structured_binding, "dataset_path", "")
            else str(tool_input.get("dataset_path", "") or tool_input.get("path", "") or "").strip()
        ),
        "active_pdf": str(tool_input.get("path", "") or "").strip(),
    }
