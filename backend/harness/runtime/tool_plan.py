from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.tooling import ToolCapability, ToolCapabilitySourceTrace, ToolCapabilityTable


@dataclass(frozen=True, slots=True)
class RuntimeToolPlan:
    plan_id: str
    session_id: str
    turn_id: str
    agent_invocation_id: str
    invocation_kind: str
    model_visible_tools: tuple[dict[str, Any], ...] = ()
    dispatchable_tool_names: tuple[str, ...] = ()
    capability_table: ToolCapabilityTable | None = None
    operation_authorization: dict[str, Any] = field(default_factory=dict)
    schema_hash: str = ""
    registry_hash: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.tool_plan"

    def __post_init__(self) -> None:
        if self.authority != "harness.runtime.tool_plan":
            raise ValueError("RuntimeToolPlan authority must be harness.runtime.tool_plan")
        if not self.plan_id:
            raise ValueError("RuntimeToolPlan requires plan_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["model_visible_tools"] = [dict(item) for item in self.model_visible_tools]
        payload["dispatchable_tool_names"] = list(self.dispatchable_tool_names)
        payload["capability_table"] = self.capability_table.to_dict() if self.capability_table is not None else {}
        payload["operation_authorization"] = dict(self.operation_authorization or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def build_runtime_tool_plan(
    *,
    runtime_assembly: Any,
    invocation_kind: str,
    tool_definitions_by_name: dict[str, Any] | None = None,
) -> RuntimeToolPlan:
    assembly = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    definition_by_name = dict(tool_definitions_by_name or {})
    visible_tools = tuple(
        sorted(
            (
                dict(item)
                for item in list(assembly.get("available_tools") or [])
                if isinstance(item, dict)
                and _visible_in_invocation(
                    dict(item),
                    invocation_kind=invocation_kind,
                    definition=definition_by_name.get(_tool_name(dict(item))),
                )
            ),
            key=lambda item: _tool_name(item),
        )
    )
    capabilities = []
    for tool in visible_tools:
        name = _tool_name(tool)
        if not name:
            continue
        definition = definition_by_name.get(name)
        operation_id = str(tool.get("operation_id") or getattr(definition, "operation_id", "") or name)
        capabilities.append(
            ToolCapability(
                operation_id=operation_id,
                tool_name=name,
                visible=True,
                dispatchable=True,
                requires_approval=False,
                source_trace=(ToolCapabilitySourceTrace(source="runtime_assembly", detail=name),),
                metadata={
                    "read_only": bool(getattr(definition, "is_read_only", False)),
                    "destructive": bool(getattr(definition, "is_destructive", False)),
                    "tool_view": dict(tool),
                },
            )
        )
    table = ToolCapabilityTable(
        table_id=f"tool-capability:{assembly.get('turn_id') or 'turn'}:{invocation_kind}",
        environment_id=str(dict(assembly.get("task_environment") or {}).get("environment_id") or ""),
        capabilities=tuple(sorted(capabilities, key=lambda item: (item.operation_id, item.tool_name))),
        source_trace=(ToolCapabilitySourceTrace(source="runtime_tool_plan", detail=invocation_kind),),
    )
    schema_hash = _stable_hash(visible_tools)
    registry_hash = _stable_hash(table.to_dict())
    return RuntimeToolPlan(
        plan_id=f"rttoolplan:{assembly.get('turn_id') or 'turn'}:{invocation_kind}:{schema_hash[:12]}",
        session_id=str(assembly.get("session_id") or ""),
        turn_id=str(assembly.get("turn_id") or ""),
        agent_invocation_id=str(assembly.get("agent_invocation_id") or ""),
        invocation_kind=str(invocation_kind or ""),
        model_visible_tools=visible_tools,
        dispatchable_tool_names=tuple(sorted(table.dispatchable_tools)),
        capability_table=table,
        operation_authorization=dict(assembly.get("operation_authorization") or {}),
        schema_hash=schema_hash,
        registry_hash=registry_hash,
        diagnostics={
            "visible_tool_count": len(visible_tools),
            "dispatchable_tool_count": len(table.dispatchable_tools),
            "source": "runtime_assembly.available_tools",
        },
    )


def tool_instances_for_runtime_tool_plan(
    *,
    tool_instances: list[Any] | tuple[Any, ...] | None,
    tool_plan: RuntimeToolPlan | dict[str, Any],
) -> list[Any]:
    plan = tool_plan.to_dict() if hasattr(tool_plan, "to_dict") else dict(tool_plan or {})
    visible = {
        str(item.get("tool_name") or item.get("name") or "").strip()
        for item in list(plan.get("model_visible_tools") or [])
        if isinstance(item, dict) and str(item.get("tool_name") or item.get("name") or "").strip()
    }
    if not visible:
        visible = {
            str(item or "").strip()
            for item in list(plan.get("dispatchable_tool_names") or [])
            if str(item or "").strip()
        }
    if not visible:
        return []
    return [
        tool
        for tool in list(tool_instances or [])
        if str(getattr(tool, "name", "") or "").strip() in visible
    ]


def _stable_hash(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _tool_name(tool: dict[str, Any]) -> str:
    return str(tool.get("tool_name") or tool.get("name") or "").strip()


def _visible_in_invocation(tool: dict[str, Any], *, invocation_kind: str, definition: Any | None) -> bool:
    if str(invocation_kind or "").strip() != "single_agent_turn":
        return True
    if definition is not None:
        return bool(getattr(definition, "is_read_only", False))
    return bool(tool.get("read_only") is True)
