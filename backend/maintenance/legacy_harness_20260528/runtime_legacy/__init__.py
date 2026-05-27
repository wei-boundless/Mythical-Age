from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent_request import AgentRunRequest
    from .agent_services import AgentRuntimeServices
    from .config import (
        AgentRuntimeConfig,
        AgentRuntimeProfileConfig,
        CloseoutPolicy,
        ControlPolicy,
        EvidencePolicy,
        ModePolicy,
        PlanningPolicy,
        ToolPolicy,
        VerificationPolicy,
        build_agent_runtime_config,
    )
    from .context import AgentRunContext
    from .coordination_request import CoordinationStageAgentRunRequest
    from .compiler import RuntimeCompilationResult, RuntimeCompiler
    from .envelope import RuntimeEnvelope
    from .execution_policy import execution_permit_diagnostics, resolve_agent_execution_permit
    from .graph_config import (
        GraphHarnessConfig,
        build_graph_harness_config_from_runtime_spec,
        graph_harness_config_coordination_task,
        graph_harness_config_dispatch_payload,
        graph_harness_config_from_dict,
        graph_harness_config_from_run_diagnostics,
        graph_harness_config_runtime_spec_payload,
    )
    from .invocation_packet import RuntimeInvocationPacket

__all__ = [
    "AgentRunContext",
    "AgentRunRequest",
    "AgentRuntimeConfig",
    "AgentRuntimeProfileConfig",
    "AgentRuntimeServices",
    "CloseoutPolicy",
    "CoordinationStageAgentRunRequest",
    "ControlPolicy",
    "EvidencePolicy",
    "GraphHarnessConfig",
    "ModePolicy",
    "PlanningPolicy",
    "RuntimeCompilationResult",
    "RuntimeCompiler",
    "RuntimeEnvelope",
    "RuntimeInvocationPacket",
    "ToolPolicy",
    "VerificationPolicy",
    "build_agent_runtime_config",
    "build_graph_harness_config_from_runtime_spec",
    "execution_permit_diagnostics",
    "graph_harness_config_coordination_task",
    "graph_harness_config_dispatch_payload",
    "graph_harness_config_from_run_diagnostics",
    "graph_harness_config_from_dict",
    "graph_harness_config_runtime_spec_payload",
    "resolve_agent_execution_permit",
]


def __getattr__(name: str):
    if name in {
        "AgentRuntimeConfig",
        "AgentRuntimeProfileConfig",
        "CloseoutPolicy",
        "ControlPolicy",
        "EvidencePolicy",
        "ModePolicy",
        "PlanningPolicy",
        "ToolPolicy",
        "VerificationPolicy",
        "build_agent_runtime_config",
    }:
        from . import config

        return getattr(config, name)
    if name == "AgentRunContext":
        from .context import AgentRunContext

        return AgentRunContext
    if name in {"execution_permit_diagnostics", "resolve_agent_execution_permit"}:
        from . import execution_policy

        return getattr(execution_policy, name)
    if name == "AgentRunRequest":
        from .agent_request import AgentRunRequest

        return AgentRunRequest
    if name == "AgentRuntimeServices":
        from .agent_services import AgentRuntimeServices

        return AgentRuntimeServices
    if name == "CoordinationStageAgentRunRequest":
        from .coordination_request import CoordinationStageAgentRunRequest

        return CoordinationStageAgentRunRequest
    if name in {"RuntimeCompilationResult", "RuntimeCompiler"}:
        from . import compiler

        return getattr(compiler, name)
    if name == "RuntimeEnvelope":
        from .envelope import RuntimeEnvelope

        return RuntimeEnvelope
    if name == "RuntimeInvocationPacket":
        from .invocation_packet import RuntimeInvocationPacket

        return RuntimeInvocationPacket
    if name in {
        "GraphHarnessConfig",
        "build_graph_harness_config_from_runtime_spec",
        "graph_harness_config_coordination_task",
        "graph_harness_config_dispatch_payload",
        "graph_harness_config_from_run_diagnostics",
        "graph_harness_config_from_dict",
        "graph_harness_config_runtime_spec_payload",
    }:
        from . import graph_config

        return getattr(graph_config, name)
    raise AttributeError(name)


