from __future__ import annotations

import time
from typing import Any

from runtime.context_management.system_asset_lines import (
    HarnessControlSpineLine,
    build_system_asset_line_inventory,
)
from runtime.context_management.system_line_controller import build_context_line_state_inventory
from runtime.prompt_accounting import build_provider_cache_log_view

from ..harness_spine_contract import task_executor_runner_contract_inventory
from ..control_action_schema import control_output_line_declarations, control_output_line_id
from .diagnostics import diagnose_runtime_topology_projection
from .nodes import ContextContractManifest


RUNTIME_TOPOLOGY_SCHEMA = "runtime_topology_projection"
RUNTIME_TOPOLOGY_AUTHORITY = "harness.runtime.context_contract.inspection_payload.runtime_topology_projection"


def build_context_contract_inspection_payload(manifest: ContextContractManifest | dict[str, Any]) -> dict[str, Any]:
    payload = manifest.to_dict() if isinstance(manifest, ContextContractManifest) else dict(manifest or {})
    nodes = [dict(item) for item in list(payload.get("nodes") or []) if isinstance(item, dict)]
    edges = [dict(item) for item in list(payload.get("edges") or []) if isinstance(item, dict)]
    return {
        "authority": "harness.runtime.context_contract.inspection_payload",
        "packet_id": str(payload.get("packet_id") or ""),
        "invocation_kind": str(payload.get("invocation_kind") or ""),
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "agent_visible_count": sum(1 for node in nodes if node.get("visibility") == "agent_visible"),
            "hidden_transport_count": sum(1 for node in nodes if node.get("visibility") == "provider_transport"),
            "issue_count": int(dict(payload.get("diagnostics") or {}).get("issue_count") or 0),
        },
        "agent_domains": _group(nodes, "agent_domain"),
        "control_signals": _group(nodes, "control_signal"),
        "time_scopes": _group(nodes, "time_scope"),
        "physical_lanes": _group(nodes, "physical_lane"),
        "connection_contracts": _group(nodes, "connection_contract_ref"),
        "control_layers": _group(nodes, "control_layer"),
        "visibility": _group(nodes, "visibility"),
        "cache_tiers": _group(nodes, "cache_tier"),
        "edge_kinds": _group_edges(edges, "edge_kind"),
        "edge_authorities": _group_edges(edges, "authority"),
        "edge_physical_lanes": _group_edges(edges, "physical_lane"),
        "edge_connection_contracts": _group_edges(edges, "connection_contract_ref"),
        "manifest": payload,
    }


def build_runtime_topology_projection(
    runtime: Any | None = None,
    *,
    session_id: str = "",
) -> dict[str, Any]:
    nodes = _runtime_topology_nodes()
    edges = _runtime_topology_edges()
    line_governance = _runtime_line_governance_projection()
    normalized_session_id = str(session_id or "").strip()
    host = _runtime_host(runtime)
    runtime_available = runtime is not None
    runtime_host_available = host is not None
    diagnostics = diagnose_runtime_topology_projection(
        nodes,
        edges,
        runtime_available=runtime_available,
        runtime_host_available=runtime_host_available,
        line_governance=line_governance,
    )
    payload = {
        "schema": RUNTIME_TOPOLOGY_SCHEMA,
        "authority": RUNTIME_TOPOLOGY_AUTHORITY,
        "generated_at": time.time(),
        "scope": {
            "session_id": normalized_session_id,
            "runtime_available": runtime_available,
            "runtime_host_available": runtime_host_available,
            "runtime_host_instance_id": str(getattr(host, "instance_id", "") or "") if host is not None else "",
            "read_only": True,
        },
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "connected_edge_count": sum(1 for edge in edges if str(edge.get("status") or "") == "connected"),
            "runtime_authority": "SingleAgentRuntimeHost",
            "projection_kind": "inspection_facade",
        },
        "branches": _runtime_topology_branches(),
        "domains": _runtime_topology_domains(nodes),
        "nodes": nodes,
        "edges": edges,
        "line_governance": line_governance,
        "diagnostics": diagnostics,
        "runtime_evidence": _runtime_session_evidence(runtime, session_id=normalized_session_id)
        if normalized_session_id
        else _empty_runtime_evidence("session_id_not_requested"),
    }
    return payload


def _group(nodes: list[dict[str, Any]], key: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for node in nodes:
        value = str(node.get(key) or "unknown")
        grouped.setdefault(value, []).append(str(node.get("node_id") or ""))
    return grouped


def _group_edges(edges: list[dict[str, Any]], key: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for edge in edges:
        value = str(edge.get(key) or "unknown")
        grouped.setdefault(value, []).append(str(edge.get("edge_id") or ""))
    return grouped


def _runtime_topology_branches() -> list[dict[str, str]]:
    return [
        {"id": "all", "label": "全部网络"},
        {"id": "entry", "label": "入口"},
        {"id": "control", "label": "控制"},
        {"id": "context", "label": "上下文"},
        {"id": "action", "label": "动作"},
        {"id": "transport", "label": "传输"},
        {"id": "ledger", "label": "账本"},
        {"id": "memory", "label": "热账本"},
        {"id": "diagnostic", "label": "诊断"},
    ]


def _runtime_line_governance_projection() -> dict[str, Any]:
    asset_inventory = build_system_asset_line_inventory()
    line_state_inventory = build_context_line_state_inventory()
    control_output_lines = tuple(control_output_line_declarations())
    harness_spine_lines = _harness_control_spine_lines()
    harness_spine_contracts = tuple(task_executor_runner_contract_inventory())
    asset_diagnostics = dict(asset_inventory.get("diagnostics") or {})
    line_state_summary = dict(line_state_inventory.get("summary") or {})
    return {
        "schema": "runtime_line_governance_projection",
        "authority": f"{RUNTIME_TOPOLOGY_AUTHORITY}.line_governance",
        "summary": {
            "system_asset_line_count": int(dict(asset_inventory.get("summary") or {}).get("line_count") or 0),
            "context_line_state_count": int(line_state_summary.get("line_state_count") or 0),
            "control_output_line_count": len(control_output_lines),
            "harness_control_spine_line_count": len(harness_spine_lines),
            "harness_runtime_spine_contract_count": len(harness_spine_contracts),
            "system_asset_issue_count": int(asset_diagnostics.get("issue_count") or 0),
        },
        "system_asset_lines": asset_inventory,
        "context_line_states": line_state_inventory,
        "control_output_lines": [line.to_dict() for line in control_output_lines],
        "harness_control_spine_lines": [line.to_dict() for line in harness_spine_lines],
        "harness_runtime_spine_contracts": [dict(item) for item in harness_spine_contracts],
    }


def _harness_control_spine_lines() -> tuple[HarnessControlSpineLine, ...]:
    return tuple(
        _harness_control_spine_line(
            action_type="respond",
            receipt_ref="",
            commit_ref="harness.runtime.output_commit_authority",
            terminal_policy="assistant final must pass OutputCommitAuthority",
        )
        + _harness_control_spine_line(
            action_type="ask_user",
            receipt_ref="",
            commit_ref="harness.runtime.output_commit_authority",
            terminal_policy="assistant question must pass OutputCommitAuthority",
        )
        + _harness_control_spine_line(
            action_type="block",
            receipt_ref="",
            commit_ref="harness.runtime.output_commit_authority",
            terminal_policy="blocked response must pass OutputCommitAuthority",
        )
        + _harness_control_spine_line(
            action_type="request_task_run",
            receipt_ref="task_run_contract_seed",
            commit_ref="",
            terminal_policy="task resource allocation requires admitted task contract seed",
        )
        + _harness_control_spine_line(
            action_type="active_work_control",
            receipt_ref="harness.current_work_receipt.CurrentWorkBoundaryReceipt",
            commit_ref="",
            terminal_policy="active work control requires CurrentWorkBoundaryReceipt and admission",
        )
        + _harness_control_spine_line(
            action_type="resume_task_recovery",
            receipt_ref="harness.recovery_receipt.RecoveryReceipt",
            commit_ref="",
            terminal_policy="task recovery resume requires enforced RecoveryReceipt and route",
        )
        + _harness_control_spine_line(
            action_type="pause_for_user_steer",
            receipt_ref="task_execution_action_surface",
            commit_ref="",
            terminal_policy="pause for user steer is only valid inside explicit task execution action surface",
        )
    )


def _harness_control_spine_line(
    *,
    action_type: str,
    receipt_ref: str,
    commit_ref: str,
    terminal_policy: str,
) -> tuple[HarnessControlSpineLine, ...]:
    action = str(action_type or "").strip()
    if not action:
        return ()
    return (
        HarnessControlSpineLine(
            control_line_id=f"harness_control_spine:{action}",
            action_type=action,
            model_action_ref=f"harness.loop.model_action_protocol:{action}",
            packet_context_ref="harness.runtime.packet_context.RuntimePacketContext",
            receipt_ref=receipt_ref,
            admission_ref=f"harness.loop.admission:{action}",
            permit_ref="harness.loop.action_permit.ActionPermit",
            tool_plan_ref="harness.runtime.packet_context.RuntimePacketContext.tool_plan",
            tool_invocation_ref="runtime.tool_runtime.tool_control_plane.RuntimeToolControlPlane",
            runtime_gateway_ref="harness.runtime.runtime_gateway.RuntimeGateway",
            commit_ref=commit_ref,
            projection_ref="harness.runtime.context_contract.inspection_payload.runtime_topology_projection",
            terminal_policy=terminal_policy,
            control_output_line_ref=control_output_line_id(action),
        ),
    )


def _runtime_topology_nodes() -> list[dict[str, Any]]:
    return [
        _node(
            "runtime-facade",
            "HarnessRuntimeFacade",
            "API adapter",
            "domain",
            "entry",
            "backend/harness/entrypoint/runtime_facade.py",
            "Present",
            "RuntimeEntryDomain",
            "harness.entrypoint.runtime_facade",
            "接收 API 输入，装配 runtime 事实，并把普通 turn 交给 single-agent loop。",
            x=8,
            y=46,
            agent_role="request_adapter",
            control_layer="observe_dispatch",
            owned_signals=["runtime_branch", "session_context", "turn_input_facts"],
            state_read_policy="read session record, runtime settings, TurnMemory recovery and continuation diagnostics",
            state_write_policy="append runtime events through host-owned services only",
        ),
        _node(
            "runtime-host",
            "SingleAgentRuntimeHost",
            "runtime service host",
            "domain",
            "control",
            "backend/harness/runtime/single_agent_host.py",
            "Self / Present / Future",
            "RuntimeSpineDomain",
            "harness.runtime.single_agent_host",
            "持有 event log、runtime gateway、stores、gates、TurnMemory 和 tool control plane。",
            x=21,
            y=46,
            agent_role="runtime_service_owner",
            control_layer="runtime_spine",
            owned_signals=["event_log", "runtime_gateway", "operation_gate", "turn_memory_store"],
            state_read_policy="read host-owned stores and gates",
            state_write_policy="only host-owned services mutate runtime state",
        ),
        _node(
            "agent-runtime-services",
            "AgentRuntimeServices",
            "explicit service table",
            "contract",
            "control",
            "backend/harness/runtime/services.py",
            "Self",
            "RuntimeServiceTableDomain",
            "harness.runtime.services",
            "把 loop/executor 需要的服务显式传入，避免 executor 回调 facade 重新决定意图。",
            x=34,
            y=46,
            agent_role="service_table",
            control_layer="dependency_boundary",
            owned_signals=["service_binding"],
            state_read_policy="read host-owned service references",
            state_write_policy="no direct state writes",
        ),
        _node(
            "request-facts",
            "RequestFacts",
            "current turn facts",
            "domain",
            "entry",
            "backend/harness/runtime/request_facts.py",
            "Present",
            "RequestFactsDomain",
            "harness.runtime.request_facts",
            "记录用户文本、附件、active work、recent outcome 和环境事实，不判断最终意图。",
            x=20,
            y=22,
            agent_role="fact_collector",
            control_layer="observe",
            owned_signals=["turn_input_facts"],
            state_read_policy="read request and session metadata",
            state_write_policy="emit facts only",
        ),
        _node(
            "current-work-boundary",
            "CurrentWorkBoundary",
            "work boundary",
            "contract",
            "control",
            "backend/harness/entrypoint/current_work_boundary.py",
            "Present",
            "WorkBoundaryDomain",
            "harness.entrypoint.current_work_boundary",
            "裁决当前输入是普通 turn、活动任务控制、补充信息还是需要阻断的边界。",
            x=36,
            y=22,
            agent_role="work_boundary_decider",
            control_layer="boundary_policy",
            owned_signals=["current_work_boundary"],
            state_read_policy="read facts and active work state",
            state_write_policy="emit boundary receipt only",
        ),
        _node(
            "single-agent-turn-loop",
            "run_single_agent_turn",
            "execution loop",
            "domain",
            "action",
            "backend/harness/loop/single_agent_turn.py",
            "Present / Future",
            "ExecutionLoopDomain",
            "harness.loop.single_agent_turn",
            "执行单 agent turn，启动 TurnMemory，编译 packet，调用模型，驱动工具批次和最终提交。",
            x=52,
            y=22,
            agent_role="turn_execution_loop",
            control_layer="execute",
            owned_signals=["turn_run", "tool_round", "runtime_control_signal", "final_answer"],
            state_read_policy="read runtime services and model/tool observations",
            state_write_policy="write through RuntimeEventLog, RuntimeGateway, TurnMemory, OutputCommitAuthority",
        ),
        _node(
            "runtime-compiler",
            "RuntimeCompiler",
            "model packet assembler",
            "contract",
            "context",
            "backend/harness/runtime/compiler.py",
            "Self / Past / Present / Future",
            "RuntimePacketDomain",
            "harness.runtime.compiler",
            "组装模型可见 operating contract、context projection、dynamic runtime payload 和工具面。",
            x=52,
            y=48,
            agent_role="runtime_packet_assembler",
            control_layer="assemble",
            owned_signals=["runtime_invocation_packet", "prompt_projection"],
            state_read_policy="read session context, context pipeline outputs, tool surface, TurnMemory recovery",
            state_write_policy="emit packet and evidence projection refs",
        ),
        _node(
            "context-pipeline",
            "ContextPipeline",
            "context candidates to PhysicalContextInputs",
            "physical",
            "context",
            "backend/runtime/context_management/context_pipeline.py",
            "Self / Past / Present",
            "ContextPipelineDomain",
            "runtime.context_management.context_pipeline",
            "把候选上下文收束为 draft/final PhysicalContextInputs；ledger 只 enrich current append。",
            x=38,
            y=70,
            agent_role="context_candidate_normalizer",
            control_layer="retrieve_assemble",
            owned_signals=["context_candidates", "PhysicalContextInputs", "provider_visible_append_enrichment"],
            state_read_policy="read context candidates and capability filters",
            state_write_policy="write provider-visible and physical context artifacts through owning ledgers",
        ),
        _node(
            "physical-context-plan",
            "PhysicalContextPlanDiagnostics",
            "read-only lane diagnostics",
            "physical",
            "context",
            "backend/runtime/context_management/physical_context_plan.py",
            "Physical",
            "PhysicalDiagnosticsDomain",
            "runtime.context_management.physical_context_plan",
            "只读检查 assembler 输出的四段 lane 和 cache spine，不写入 provider payload lane。",
            x=54,
            y=70,
            agent_role="physical_lane_diagnostics_reader",
            control_layer="diagnose",
            owned_signals=["physical_lane_diagnostics"],
            state_read_policy="read assembler-emitted lane/index metadata",
            state_write_policy="emit diagnostics only",
            physical_lane_policy="global_static_prefix/provider_visible_context_prefix/current_turn_tail/never_replay_tail",
        ),
        _node(
            "physical-context-assembler",
            "PhysicalContextAssembler",
            "byte-stable splice",
            "physical",
            "context",
            "backend/runtime/context_management/physical_context_assembler.py",
            "Past / Present",
            "PhysicalSpliceDomain",
            "runtime.context_management.physical_context_assembler",
            "按 static prefix、confirmed old frame、current append、dynamic tail 的顺序拼接。",
            x=70,
            y=70,
            agent_role="physical_splice_assembler",
            control_layer="assemble",
            owned_signals=["physical_context_assembly"],
            state_read_policy="read confirmed frame and current append",
            state_write_policy="emit assembled physical context and frame replay diagnostics",
        ),
        _node(
            "model-runtime",
            "ModelRuntime",
            "provider invocation",
            "transport",
            "transport",
            "backend/runtime/model_gateway/model_runtime.py",
            "HiddenTransport",
            "ProviderInvocationDomain",
            "runtime.model_gateway.model_runtime",
            "调用模型 provider，记录 provider usage、payload manifest、cache bus 和 TurnMemory provider refs。",
            x=84,
            y=48,
            agent_role="provider_invoker",
            control_layer="execute",
            owned_signals=["provider_request", "provider_usage", "model_response"],
            state_read_policy="read provider payload and model settings",
            state_write_policy="record provider refs through prompt accounting and TurnMemory stores",
        ),
        _node(
            "provider-payload-manifest",
            "ProviderPayloadManifest",
            "provider bytes manifest",
            "transport",
            "transport",
            "backend/runtime/model_gateway/provider_payload.py",
            "HiddenTransport",
            "ProviderPayloadDomain",
            "runtime.model_gateway.provider_payload",
            "记录 provider messages、tools、params、transport contract、physical cache spine 和 serialized hash。",
            x=84,
            y=70,
            agent_role="provider_payload_recorder",
            control_layer="record",
            owned_signals=["provider_payload_manifest"],
            state_read_policy="read serialized provider request",
            state_write_policy="write manifest record only",
        ),
        _node(
            "provider-cache-bus",
            "ProviderCacheBus",
            "prefix cache verdict",
            "diagnostic",
            "diagnostic",
            "backend/runtime/prompt_accounting/provider_cache_bus.py",
            "Diagnostic",
            "CacheDiagnosticDomain",
            "runtime.prompt_accounting.provider_cache_bus",
            "输出 latest prefix health、under-read、first missing prefix identity；总 hit rate 只能辅助观察。",
            x=84,
            y=88,
            agent_role="cache_diagnostic_projection",
            control_layer="record_present",
            owned_signals=["provider_cache_log", "prefix_cache_health"],
            state_read_policy="read provider usage and prefix cache health",
            state_write_policy="append provider cache bus records",
        ),
        _node(
            "runtime-gateway",
            "RuntimeGateway",
            "typed control fact gateway",
            "diagnostic",
            "control",
            "backend/harness/runtime/runtime_gateway.py",
            "Present / Future",
            "RuntimeControlFactDomain",
            "harness.runtime.runtime_gateway",
            "在 RuntimeEventLog 上发布、观察、消费 typed control facts；不决定意图、不授权、不提交。",
            x=66,
            y=48,
            agent_role="control_fact_gateway",
            control_layer="record_drain",
            owned_signals=["runtime_control_signal", "runtime_evidence_projection"],
            state_read_policy="read RuntimeEventLog",
            state_write_policy="append control fact events only",
        ),
        _node(
            "model-action-lifecycle",
            "ModelActionLifecycle",
            "action request normalizer",
            "contract",
            "action",
            "backend/harness/loop/execution_kernel.py",
            "Present",
            "ModelActionDomain",
            "harness.loop.execution_kernel",
            "把模型动作请求转成生命周期记录，进入 admission 和 permit，而不是由 executor 猜动作。",
            x=66,
            y=22,
            agent_role="model_action_normalizer",
            control_layer="normalize",
            owned_signals=["model_action_request", "action_lifecycle_event"],
            state_read_policy="read model response protocol",
            state_write_policy="append lifecycle event",
        ),
        _node(
            "admission-decision",
            "AdmissionDecision",
            "action admission",
            "contract",
            "action",
            "backend/harness/loop/admission.py",
            "Present",
            "ActionAdmissionDomain",
            "harness.loop.admission",
            "判定模型动作是否允许进入工具执行、任务控制或最终输出路径。",
            x=78,
            y=22,
            agent_role="action_admission_authority",
            control_layer="authorize",
            owned_signals=["admission_decision"],
            state_read_policy="read model action request and runtime boundary",
            state_write_policy="emit admission decision",
        ),
        _node(
            "action-permit",
            "ActionPermit",
            "tool permit identity",
            "contract",
            "action",
            "backend/harness/loop/action_permit.py",
            "Present",
            "ActionPermitDomain",
            "harness.loop.action_permit",
            "生成工具执行 permit，把可执行动作和权限身份绑定到 tool invocation。",
            x=90,
            y=22,
            agent_role="tool_permission_identity",
            control_layer="authorize",
            owned_signals=["action_permit"],
            state_read_policy="read admission decision and operation gate",
            state_write_policy="emit permit only",
        ),
        _node(
            "tool-control-plane",
            "RuntimeToolControlPlane",
            "tool execution boundary",
            "transport",
            "action",
            "backend/runtime/tool_runtime/tool_control_plane.py",
            "Present",
            "ToolExecutionDomain",
            "runtime.tool_runtime.tool_control_plane",
            "执行 permit 授权后的工具调用，返回 observation，不重新选择用户目标。",
            x=90,
            y=40,
            agent_role="tool_execution_boundary",
            control_layer="execute",
            owned_signals=["tool_invocation", "tool_observation"],
            state_read_policy="read ActionPermit and operation gate",
            state_write_policy="write tool observations and runtime events",
        ),
        _node(
            "output-commit-authority",
            "OutputCommitAuthority",
            "assistant final commit gate",
            "ledger",
            "ledger",
            "backend/harness/runtime/output_commit_authority.py",
            "Future",
            "OutputCommitDomain",
            "harness.runtime.output_commit_authority",
            "唯一 assistant final commit gate，防止旧流、工具输出或 debug 文本误提交为最终答复。",
            x=66,
            y=88,
            agent_role="assistant_output_commit_authority",
            control_layer="commit",
            owned_signals=["session_output_commit", "final_answer_commit"],
            state_read_policy="read final answer candidate and runtime state",
            state_write_policy="write committed assistant output and commit event",
        ),
        _node(
            "provider-visible-append-ledger",
            "ProviderVisibleAppendLedger",
            "current append confirmation ledger",
            "ledger",
            "ledger",
            "backend/runtime/context_management/provider_visible_append_ledger.py",
            "Present -> Past",
            "EvidenceTimelineDomain",
            "runtime.context_management.provider_visible_append_ledger",
            "记录 provider-visible current append candidates 的确认状态；不负责下一轮 replay，replay 顺序由 physical prefix frame 承担。",
            x=36,
            y=88,
            agent_role="provider_visible_append_ledger",
            control_layer="record",
            owned_signals=["provider_visible_append_candidate", "provider_visible_append_confirmation"],
            state_read_policy="read current append provider-visible material",
            state_write_policy="append provider success confirmation records",
        ),
        _node(
            "physical-prefix-frame-ledger",
            "PhysicalPrefixFrameLedger",
            "confirmed physical frame",
            "ledger",
            "ledger",
            "backend/runtime/context_management/physical_prefix_frame_ledger.py",
            "Past",
            "PhysicalFrameDomain",
            "runtime.context_management.physical_prefix_frame_ledger",
            "维护 confirmed physical prefix frame，让下一轮 Past 可以 byte-stable replay。",
            x=20,
            y=88,
            agent_role="physical_prefix_frame_ledger",
            control_layer="record_recover",
            owned_signals=["physical_prefix_frame"],
            state_read_policy="read sealed provider-visible entries",
            state_write_policy="write confirmed frame refs",
        ),
        _node(
            "turn-memory-store",
            "TurnMemoryStore",
            "turn hot ledger",
            "memory",
            "memory",
            "backend/runtime/turn_memory/turn_memory_store.py",
            "Present / Future",
            "TurnHotLedgerDomain",
            "runtime.turn_memory.store",
            "记录 provider refs、manifest refs、draft/final refs、tool rounds、commit state、recovery state。",
            x=18,
            y=70,
            agent_role="turn_hot_ledger",
            control_layer="record_recover",
            owned_signals=["turn_memory", "checkpoint", "commit_result", "tool_round"],
            state_read_policy="read current session turn memory",
            state_write_policy="write turn hot ledger only",
        ),
        _node(
            "turn-memory-recovery-context",
            "TurnMemoryRecoveryContext",
            "recoverable turn cursor",
            "memory",
            "memory",
            "backend/runtime/turn_memory/turn_memory_recovery_context.py",
            "Present / Future",
            "TurnRecoveryDomain",
            "runtime.turn_memory.recovery_context",
            "从 TurnMemory 选择可恢复 turn，输出 retry_commit、retry_frame_promotion、recover_from_checkpoint 等恢复上下文。",
            x=8,
            y=70,
            agent_role="turn_recovery_projection",
            control_layer="recover",
            owned_signals=["turn_memory_recovery"],
            state_read_policy="read TurnMemory session projection and checkpoints",
            state_write_policy="no direct writes",
        ),
    ]


def _runtime_topology_edges() -> list[dict[str, Any]]:
    return [
        _edge(
            "facade-to-host",
            "runtime-facade",
            "runtime-host",
            "facade 绑定 runtime host",
            "bind_runtime_host",
            "runtime host instance",
            "harness.entrypoint.runtime_facade",
            "Runtime host missing -> app runtime not ready",
            payload_identity="runtime_host.instance_id",
        ),
        _edge(
            "host-to-services",
            "runtime-host",
            "agent-runtime-services",
            "host-owned services 显式传递",
            "bind_services",
            "host-owned stores/gates/service refs",
            "harness.runtime.services",
            "service table missing -> fail runtime initialization",
            payload_identity="runtime host service refs",
        ),
        _edge(
            "facade-to-request-facts",
            "runtime-facade",
            "request-facts",
            "API 请求转成 turn facts",
            "observe_request",
            "session_id + turn_id + user message + attachments",
            "harness.runtime.request_facts",
            "missing request facts -> explicit failure before model turn",
            payload_identity="session_id + turn_id",
        ),
        _edge(
            "request-facts-to-boundary",
            "request-facts",
            "current-work-boundary",
            "事实进入当前工作边界",
            "decide_boundary",
            "TurnInputFacts",
            "harness.entrypoint.current_work_boundary",
            "ambiguous active work -> boundary receipt denial or user-visible control response",
            payload_identity="turn_id + active work ref",
        ),
        _edge(
            "boundary-to-loop",
            "current-work-boundary",
            "single-agent-turn-loop",
            "普通 turn 进入执行循环",
            "dispatch_single_agent_turn",
            "CurrentWorkBoundaryReceipt",
            "harness.entrypoint.runtime_facade",
            "non-turn control -> handled by active work control path",
            payload_identity="turn_id + runtime_branch",
        ),
        _edge(
            "loop-to-turn-memory",
            "single-agent-turn-loop",
            "turn-memory-store",
            "turn 启动写入热账本",
            "create_or_get_turn",
            "session_id + turn_id + turn_run_id",
            "runtime.turn_memory.store",
            "missing session_id/turn_id -> ValueError and turn failure",
            payload_identity="session_id + turn_id",
        ),
        _edge(
            "loop-to-compiler",
            "single-agent-turn-loop",
            "runtime-compiler",
            "编译模型 invocation packet",
            "compile_packet",
            "RuntimeInvocationPacket inputs",
            "harness.runtime.compiler",
            "packet compile failure -> model turn failure before provider call",
            payload_identity="packet_id + turn_run_id",
        ),
        _edge(
            "compiler-to-context-pipeline",
            "runtime-compiler",
            "context-pipeline",
            "上下文候选进入物理拼接主干",
            "assemble_context",
            "context candidates + session context",
            "runtime.context_management.context_pipeline",
            "context assembly blocked -> runtime packet diagnostics",
            payload_identity="session_id + turn_id + context assembly id",
            cache_expectation="only stable physical prefix and confirmed frame expect provider cache read",
        ),
        _edge(
            "context-pipeline-to-physical-plan",
            "context-pipeline",
            "physical-context-plan",
            "assembler 输出进入只读物理诊断",
            "diagnose_physical_context",
            "assembled message specs + assembler lane/index metadata",
            "runtime.context_management.context_pipeline",
            "missing assembler lane/index -> structural diagnostic",
            payload_identity="context segment id + prefix identity",
            cache_expectation="global_static_prefix/provider_visible_context_prefix are cache-relevant",
        ),
        _edge(
            "context-pipeline-to-physical-assembler",
            "context-pipeline",
            "physical-context-assembler",
            "PhysicalContextInputs 进入唯一四段拼接",
            "splice_physical_context",
            "PhysicalContextInputs(final)",
            "runtime.context_management.physical_context_assembler",
            "old frame missing -> fail closed or full reinjection diagnostic",
            payload_identity="physical frame id + current append hash",
            cache_expectation="confirmed old frame must replay byte-identically",
        ),
        _edge(
            "assembler-to-provider-payload",
            "physical-context-assembler",
            "provider-payload-manifest",
            "物理拼接进入 provider payload manifest",
            "serialize_provider_payload",
            "messages + tools + transport contract",
            "runtime.model_gateway.provider_payload",
            "unplanned message -> never_cache segment diagnostic",
            payload_identity="provider_payload_manifest_ref + transport_contract_hash",
            cache_expectation="manifest records physical cache spine hash",
        ),
        _edge(
            "compiler-to-gateway-evidence",
            "runtime-compiler",
            "runtime-gateway",
            "packet evidence 投影进入 RuntimeGateway",
            "publish_evidence_projection",
            "packet context + projection_ref",
            "harness.runtime.runtime_gateway",
            "missing projection_ref -> ValueError, no silent fallback",
            payload_identity="runtime_invocation_packet_ref",
        ),
        _edge(
            "compiler-to-model-runtime",
            "runtime-compiler",
            "model-runtime",
            "packet 交给 provider 调用",
            "invoke_model",
            "RuntimeInvocationPacket + provider request",
            "harness.loop.model_action_runtime",
            "provider failure -> model runtime error and recoverable turn state",
            payload_identity="request_id + turn_run_id",
        ),
        _edge(
            "model-runtime-to-provider-payload",
            "model-runtime",
            "provider-payload-manifest",
            "provider request bytes 记录为 manifest",
            "record_payload_manifest",
            "provider serialized request + segment boundaries",
            "runtime.model_gateway.provider_payload",
            "manifest write failure -> diagnostics, no cache health authority",
            payload_identity="provider_payload_manifest_ref",
            cache_expectation="manifest supplies physical cache spine inputs",
        ),
        _edge(
            "provider-payload-to-cache-bus",
            "provider-payload-manifest",
            "provider-cache-bus",
            "provider usage 写入 cache bus",
            "cache_diagnose",
            "ProviderCacheBusRecord + prefix health",
            "runtime.prompt_accounting.provider_cache_bus",
            "first missing expected prefix -> provider_under_read diagnostic",
            payload_identity="bus_record_id + request_id + physical_cache_spine_hash",
            cache_expectation="expected prefix coverage is primary; hit rate is secondary",
            diagnostics_key="provider_cache_log.summary.latest_prefix_health",
        ),
        _edge(
            "model-runtime-to-turn-memory",
            "model-runtime",
            "turn-memory-store",
            "provider refs 写入 turn 热账本",
            "append_provider_request_ref",
            "request ref + manifest ref + current append hash",
            "runtime.turn_memory.store",
            "closed turn memory -> no mutation",
            payload_identity="session_id + turn_id + provider request ref",
        ),
        _edge(
            "model-runtime-to-action-lifecycle",
            "model-runtime",
            "model-action-lifecycle",
            "模型返回动作合同",
            "normalize_model_action",
            "ModelActionRequest",
            "harness.loop.model_action_protocol",
            "invalid action protocol -> repair or explicit model call recovery",
            payload_identity="action_request_ref + turn_id",
        ),
        _edge(
            "action-lifecycle-to-admission",
            "model-action-lifecycle",
            "admission-decision",
            "动作进入准入裁决",
            "admit_action",
            "ModelActionRequest + active work context",
            "harness.loop.admission",
            "denied action -> visible denial, no replacement action invented",
            payload_identity="action_request_ref",
        ),
        _edge(
            "admission-to-permit",
            "admission-decision",
            "action-permit",
            "准入结果绑定工具 permit",
            "issue_permit",
            "AdmissionDecision",
            "harness.loop.action_permit",
            "denied admission -> no tool permit",
            payload_identity="permit_id + action_request_ref",
        ),
        _edge(
            "permit-to-tool-control",
            "action-permit",
            "tool-control-plane",
            "permit 驱动工具执行",
            "invoke_tool",
            "ActionPermit + tool call",
            "runtime.tool_runtime.tool_control_plane",
            "permit mismatch -> denied before tool side effect",
            payload_identity="invocation_id + tool_call_id + permit_id",
        ),
        _edge(
            "tool-control-to-loop",
            "tool-control-plane",
            "single-agent-turn-loop",
            "工具 observation 回到执行循环",
            "observe_tool_result",
            "tool observation + invocation identity",
            "harness.loop.single_agent_turn",
            "tool failure -> observation visible to loop and TurnMemory tool summary",
            payload_identity="invocation_id + observation_id",
        ),
        _edge(
            "loop-to-output-commit",
            "single-agent-turn-loop",
            "output-commit-authority",
            "final answer 进入 commit gate",
            "commit_final_answer",
            "OutputCommitRequest",
            "harness.runtime.output_commit_authority",
            "commit denied -> no assistant final message",
            payload_identity="run_id + turn_id + message ref",
        ),
        _edge(
            "output-commit-to-turn-memory",
            "output-commit-authority",
            "turn-memory-store",
            "commit receipt 写回热账本",
            "record_commit_result",
            "commit receipt",
            "runtime.turn_memory.store",
            "frame promotion pending -> TurnMemory recovery can retry",
            payload_identity="session_id + turn_id + commit event ref",
        ),
        _edge(
            "provider-success-to-visible-append-ledger",
            "model-runtime",
            "provider-visible-append-ledger",
            "provider success 后确认 current append",
            "confirm_provider_visible_append_candidates",
            "current append candidates + provider success receipt",
            "runtime.context_management.provider_visible_append_ledger",
            "provider failure -> never seal",
            payload_identity="session_id + provider request ref + content hash",
            cache_expectation="confirmed append can be promoted into physical prefix frame",
        ),
        _edge(
            "append-ledger-to-prefix-frame",
            "provider-visible-append-ledger",
            "physical-prefix-frame-ledger",
            "confirmed append 生成 physical frame",
            "promote_confirmed_append_to_physical_frame",
            "confirmed append records + provider messages",
            "runtime.context_management.physical_prefix_frame_ledger",
            "frame pending -> TurnMemory retry_frame_promotion",
            payload_identity="physical_prefix_frame_id",
            cache_expectation="confirmed frame is replay cache identity",
        ),
        _edge(
            "prefix-frame-to-assembler",
            "physical-prefix-frame-ledger",
            "physical-context-assembler",
            "下一轮 confirmed frame replay",
            "replay_confirmed_frame",
            "confirmed physical prefix frame",
            "runtime.context_management.physical_prefix_frame_ledger",
            "frame unavailable -> full reinjection or diagnostic",
            payload_identity="physical_prefix_frame_id + frame hash",
            cache_expectation="byte-identical replay required",
        ),
        _edge(
            "turn-memory-to-recovery",
            "turn-memory-store",
            "turn-memory-recovery-context",
            "热账本生成恢复上下文",
            "build_recovery_context",
            "TurnMemory session projection + latest recoverable turn",
            "runtime.turn_memory.recovery_context",
            "no recoverable turn -> recovery context absent",
            payload_identity="session_id + latest turn_id + checkpoint hash",
        ),
        _edge(
            "recovery-to-facade",
            "turn-memory-recovery-context",
            "runtime-facade",
            "恢复游标进入下一轮 session context",
            "recover_next_turn",
            "turn_memory_recovery payload",
            "harness.entrypoint.runtime_facade",
            "unrecoverable state -> explicit diagnostic, no guessed continuation",
            payload_identity="session_id + recoverable turn_id",
        ),
    ]


def _node(
    node_id: str,
    title: str,
    subtitle: str,
    kind: str,
    branch: str,
    module_path: str,
    time_scope: str,
    agent_domain: str,
    authority: str,
    summary: str,
    *,
    x: int,
    y: int,
    agent_role: str,
    control_layer: str,
    owned_signals: list[str],
    state_read_policy: str,
    state_write_policy: str,
    physical_lane_policy: str = "",
) -> dict[str, Any]:
    return {
        "id": node_id,
        "title": title,
        "subtitle": subtitle,
        "kind": kind,
        "branch": branch,
        "module_path": module_path,
        "file": module_path,
        "time_scope": time_scope,
        "timeScope": time_scope,
        "agent_domain": agent_domain,
        "domain": agent_domain,
        "agent_role": agent_role,
        "control_layer": control_layer,
        "authority": authority,
        "summary": summary,
        "owned_signals": list(owned_signals),
        "state_read_policy": state_read_policy,
        "state_write_policy": state_write_policy,
        "physical_lane_policy": physical_lane_policy,
        "status": "connected",
        "x": int(x),
        "y": int(y),
    }


def _edge(
    edge_id: str,
    source: str,
    target: str,
    label: str,
    signal: str,
    payload_schema: str,
    authority: str,
    failure_route: str,
    *,
    payload_identity: str,
    status: str = "connected",
    lifecycle: str = "single_agent_turn",
    cache_expectation: str = "",
    diagnostics_key: str = "",
) -> dict[str, Any]:
    edge_kind = _edge_kind_for_signal(signal)
    physical_lane = _physical_lane_for_edge_kind(edge_kind)
    connection_contract_ref = f"runtime_topology.connection.{edge_id}"
    forbidden_route = _forbidden_route_for_edge_kind(edge_kind)
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "label": label,
        "edge_kind": edge_kind,
        "signal": signal,
        "control_signal": signal,
        "status": status,
        "payload_schema": payload_schema,
        "payload": payload_schema,
        "payload_identity": payload_identity,
        "authority": authority,
        "connection_contract_ref": connection_contract_ref,
        "physical_lane": physical_lane,
        "producer_ref": source,
        "consumer_ref": target,
        "lifecycle": lifecycle,
        "cache_expectation": cache_expectation,
        "state_read_policy": "read canonical upstream payload only",
        "state_write_policy": "write only through target authority",
        "failure_route": failure_route,
        "failureRoute": failure_route,
        "terminal_behavior": _terminal_behavior_for_edge_kind(edge_kind),
        "forbidden_route": forbidden_route,
        "forbiddenRoute": forbidden_route,
        "diagnostics_key": diagnostics_key,
    }


def _edge_kind_for_signal(signal: str) -> str:
    value = str(signal or "").strip()
    if value in {"bind_runtime_host", "bind_services"}:
        return "runtime_binding"
    if value == "observe_request":
        return "request_observation"
    if value == "decide_boundary":
        return "boundary_decision"
    if value == "dispatch_single_agent_turn":
        return "turn_dispatch"
    if value in {"create_or_get_turn", "append_provider_request_ref", "record_commit_result"}:
        return "turn_memory"
    if value in {"compile_packet", "publish_evidence_projection"}:
        return "packet_assembly"
    if value in {"assemble_context", "route_physical", "splice_physical_context"}:
        return "context_splice"
    if value in {"serialize_provider_payload", "invoke_model", "record_payload_manifest"}:
        return "provider_transport"
    if value == "cache_diagnose":
        return "cache_health"
    if value in {"normalize_model_action", "admit_action", "issue_permit"}:
        return "action_authorization"
    if value in {"invoke_tool", "observe_tool_result"}:
        return "tool_execution"
    if value == "commit_final_answer":
        return "output_commit"
    if value in {
        "confirm_provider_visible_append_candidates",
        "promote_confirmed_append_to_physical_frame",
        "replay_confirmed_frame",
    }:
        return "prefix_replay"
    if value in {"build_recovery_context", "recover_next_turn"}:
        return "recovery"
    return "runtime_connection"


def _physical_lane_for_edge_kind(edge_kind: str) -> str:
    if edge_kind == "context_splice":
        return "four_segment_physical_context"
    if edge_kind == "provider_transport":
        return "provider_payload_spine"
    if edge_kind == "cache_health":
        return "provider_cache_bus"
    if edge_kind == "prefix_replay":
        return "provider_visible_append_to_physical_prefix_frame"
    if edge_kind == "turn_memory":
        return "turn_memory_hot_journal"
    if edge_kind == "recovery":
        return "turn_memory_recovery_context"
    if edge_kind in {"action_authorization", "tool_execution", "output_commit"}:
        return "runtime_action_control"
    return "runtime_control_plane"


def _terminal_behavior_for_edge_kind(edge_kind: str) -> str:
    terminal_by_kind = {
        "runtime_binding": "startup fails before turn execution",
        "request_observation": "turn is rejected before model invocation",
        "boundary_decision": "ambiguous active work returns a boundary denial or visible control response",
        "turn_dispatch": "non-turn control is handled outside the single-agent loop",
        "turn_memory": "hot journal mutation is skipped or the turn fails visibly",
        "packet_assembly": "packet compilation fails before provider call",
        "context_splice": "context assembly emits diagnostics and does not silently invent a prompt segment",
        "provider_transport": "provider call records recoverable runtime failure",
        "cache_health": "prefix under-read is reported as provider_under_read and cannot be masked by total hit rate",
        "action_authorization": "denied action does not receive a permit",
        "tool_execution": "tool side effect is blocked before execution when permit identity mismatches",
        "output_commit": "assistant final message is not committed when output gate denies",
        "prefix_replay": "unconfirmed append is not promoted into replayable physical prefix frame",
        "recovery": "unrecoverable state returns explicit diagnostics and no guessed continuation",
    }
    return terminal_by_kind.get(str(edge_kind or ""), "connection failure is surfaced as diagnostics")


def _forbidden_route_for_edge_kind(edge_kind: str) -> str:
    forbidden_by_kind = {
        "runtime_binding": "runtime service consumers must not instantiate a second host",
        "request_observation": "request facts must not decide the user intent",
        "boundary_decision": "loop must not bypass CurrentWorkBoundary when active work exists",
        "turn_dispatch": "facade must not rewrite model action semantics after dispatch",
        "turn_memory": "sealed history must not be mutated through the hot journal",
        "packet_assembly": "compiler must not read diagnostics as a replacement contract",
        "context_splice": "hidden transport must not be projected into agent-visible prompt text",
        "provider_transport": "provider payload must not be rebuilt from frontend or monitor projections",
        "cache_health": "total hit rate must not override expected prefix coverage",
        "action_authorization": "tool/runtime action must not execute without ActionPermit",
        "tool_execution": "tool observations must not be committed without invocation identity",
        "output_commit": "assistant final output must not bypass OutputCommitAuthority",
        "prefix_replay": "failed provider output must not create a replayable prefix frame",
        "recovery": "recovery must not fabricate a continuation without TurnMemory evidence",
    }
    return forbidden_by_kind.get(str(edge_kind or ""), "target must not infer missing upstream authority")


def _runtime_topology_domains(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    domains: dict[str, list[str]] = {}
    for node in nodes:
        domain = str(node.get("agent_domain") or "UnknownDomain")
        domains.setdefault(domain, []).append(str(node.get("id") or ""))
    return [
        {"domain": domain, "node_ids": node_ids, "node_count": len(node_ids)}
        for domain, node_ids in sorted(domains.items())
    ]


def _runtime_session_evidence(runtime: Any | None, *, session_id: str) -> dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    if runtime is None:
        return _empty_runtime_evidence("runtime_unavailable")
    host = _runtime_host(runtime)
    if host is None:
        return _empty_runtime_evidence("runtime_host_unavailable")
    turn_memory = _turn_memory_session_projection(host, session_id=normalized_session_id)
    provider_cache_log = _provider_cache_log(host, session_id=normalized_session_id)
    context_recovery_package = _context_recovery_package_status(runtime, session_id=normalized_session_id)
    cache_summary = dict(provider_cache_log.get("summary") or {})
    latest_prefix_health = dict(cache_summary.get("latest_prefix_health") or {})
    return {
        "authority": f"{RUNTIME_TOPOLOGY_AUTHORITY}.session_evidence",
        "available": True,
        "session_id": normalized_session_id,
        "turn_memory": turn_memory,
        "provider_cache_log": provider_cache_log,
        "context_recovery_package": context_recovery_package,
        "cache_diagnostics": {
            "authority": "runtime.prompt_accounting.provider_cache_bus",
            "latest_status": str(cache_summary.get("latest_status") or ""),
            "latest_prefix_health": latest_prefix_health,
            "latest_under_read_tokens": int(cache_summary.get("latest_under_read_tokens") or 0),
            "latest_volatile_tokens": int(cache_summary.get("latest_volatile_tokens") or 0),
            "latest_current_turn_tail_tokens": int(cache_summary.get("latest_current_turn_tail_tokens") or 0),
            "latest_never_replay_tail_tokens": int(cache_summary.get("latest_never_replay_tail_tokens") or 0),
            "latest_unconfirmed_provider_replay_tokens": int(
                cache_summary.get("latest_unconfirmed_provider_replay_tokens") or 0
            ),
            "latest_non_cache_payload_breakdown_available": bool(
                cache_summary.get("latest_non_cache_payload_breakdown_available") is True
            ),
            "current_prefix_covered": bool(cache_summary.get("current_prefix_covered") is True),
            "current_cache_spine_hash": str(cache_summary.get("current_cache_spine_hash") or ""),
            "current_transport_contract_hash": str(cache_summary.get("current_transport_contract_hash") or ""),
            "current_context_contract_node_refs": list(cache_summary.get("current_context_contract_node_refs") or []),
            "current_context_contract_edge_refs": list(cache_summary.get("current_context_contract_edge_refs") or []),
            "current_connection_contract_refs": list(cache_summary.get("current_connection_contract_refs") or []),
            "current_agent_domains": list(cache_summary.get("current_agent_domains") or []),
            "first_missing_expected_prefix_identity": dict(
                latest_prefix_health.get("first_missing_expected_prefix_identity") or {}
            ),
            "verdict": str(latest_prefix_health.get("verdict") or ""),
        },
    }


def _empty_runtime_evidence(reason: str) -> dict[str, Any]:
    return {
        "authority": f"{RUNTIME_TOPOLOGY_AUTHORITY}.session_evidence",
        "available": False,
        "reason": str(reason or "unavailable"),
        "turn_memory": {},
        "provider_cache_log": {},
        "context_recovery_package": {},
        "cache_diagnostics": {},
    }


def _runtime_host(runtime: Any | None) -> Any | None:
    if runtime is None:
        return None
    return (
        getattr(runtime, "single_agent_runtime_host", None)
        or getattr(getattr(runtime, "harness_runtime", None), "single_agent_runtime_host", None)
    )


def _turn_memory_session_projection(host: Any, *, session_id: str) -> dict[str, Any]:
    store = getattr(host, "turn_memory_store", None)
    projector = getattr(store, "session_projection", None)
    if not callable(projector):
        return {
            "authority": "runtime.turn_memory.session_projection",
            "available": False,
            "reason": "turn_memory_store_unavailable",
            "turn_count": 0,
            "recent_turns": [],
        }
    try:
        return dict(projector(session_id, limit=20) or {})
    except Exception as exc:
        return {
            "authority": "runtime.turn_memory.session_projection",
            "available": False,
            "reason": str(exc) or "turn_memory_projection_failed",
            "turn_count": 0,
            "recent_turns": [],
        }


def _provider_cache_log(host: Any, *, session_id: str) -> dict[str, Any]:
    ledger = getattr(host, "prompt_accounting_ledger", None)
    if ledger is None:
        return {
            "authority": "runtime.prompt_accounting.provider_cache_bus",
            "available": False,
            "reason": "prompt_accounting_ledger_unavailable",
            "summary": {},
            "records": [],
        }
    try:
        payload = build_provider_cache_log_view(
            ledger,
            session_id=session_id,
            limit=50,
            authority=f"{RUNTIME_TOPOLOGY_AUTHORITY}.provider_cache_log",
        )
        payload["available"] = True
        return payload
    except Exception as exc:
        return {
            "authority": "runtime.prompt_accounting.provider_cache_bus",
            "available": False,
            "reason": str(exc) or "provider_cache_log_failed",
            "summary": {},
            "records": [],
        }


def _context_recovery_package_status(runtime: Any, *, session_id: str) -> dict[str, Any]:
    conversation_continuity = getattr(getattr(runtime, "memory_facade", None), "conversation_continuity", None)
    manager_ref = getattr(conversation_continuity, "manager", None)
    if callable(manager_ref):
        manager = manager_ref(session_id)
    elif manager_ref is not None and callable(getattr(manager_ref, "load_context_recovery_package", None)):
        manager = manager_ref
    else:
        return {
            "authority": "runtime.context_management.context_recovery_package_status",
            "present": False,
            "fresh": False,
            "reason": "conversation_continuity_unavailable",
        }
    try:
        package = manager.load_context_recovery_package()
    except Exception as exc:
        return {
            "authority": "runtime.context_management.context_recovery_package_status",
            "present": False,
            "fresh": False,
            "reason": str(exc) or "context_recovery_package_unreadable",
        }
    if not package:
        return {
            "authority": "runtime.context_management.context_recovery_package_status",
            "present": False,
            "fresh": False,
            "reason": "context_recovery_package_missing",
        }
    validation = {}
    try:
        session_manager = getattr(runtime, "session_manager", None)
        raw_messages = []
        if session_manager is not None:
            record = session_manager.get_history(session_id)
            raw_messages = list(dict(record or {}).get("messages") or [])
        validator = getattr(manager, "validate_compaction_state", None)
        if callable(validator):
            validation = dict(validator(raw_messages) or {})
    except Exception as exc:
        validation = {"ok": False, "reason": str(exc) or "compaction_state_validation_failed"}
    coverage = dict(package.get("coverage") or {})
    freshness = dict(package.get("freshness") or {})
    stale_reason = str(
        validation.get("reason") if validation and not bool(validation.get("ok")) else ""
    )
    if not stale_reason:
        stale_reason = str(freshness.get("stale_reason") or coverage.get("stale_reason") or "")
    return {
        "authority": "runtime.context_management.context_recovery_package_status",
        "present": True,
        "fresh": bool(validation.get("ok", True)) and not stale_reason,
        "source": str(package.get("source") or ""),
        "covered_message_count": int(coverage.get("covered_message_count") or 0),
        "covered_event_run_id": str(coverage.get("covered_event_run_id") or ""),
        "covered_event_offset_end": coverage.get("covered_event_offset_end"),
        "summary_hash": str(coverage.get("summary_hash") or ""),
        "source_summary_hash": str(coverage.get("source_summary_hash") or ""),
        "freshness_status": str(freshness.get("status") or ""),
        "stale_reason": stale_reason,
        "validation": validation,
    }
