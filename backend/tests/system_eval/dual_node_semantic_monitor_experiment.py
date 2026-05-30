from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from task_system import TaskFlowRegistry
from task_system.compiler.graph_harness_config_publisher import publish_graph_harness_config_for_graph
from tests.support.runtime_stubs import build_query_runtime


def _action(final_answer: str, *, diagnostics: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "authority": "harness.loop.model_action_request",
        "turn_id": "",
        "action_type": "respond",
        "public_progress_note": "正在提交节点结果。",
        "final_answer": final_answer,
        "task_contract_seed": {},
        "completion_contract": {},
        "permission_request": {},
        "diagnostics": {
            "verification": "节点已按输入完成自检。",
            **dict(diagnostics or {}),
        },
    }


def _scenario(rounds: int) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for index in range(1, rounds + 1):
        if index % 5 == 1:
            kind = "pause"
            message = f"第 {index} 轮：暂停，保留当前目标，等待我确认。"
            expected_transition = "running_to_paused"
            semantic_obligation = "暂停后不得丢失当前长任务目标。"
        elif index % 5 == 2:
            kind = "resume"
            message = f"第 {index} 轮：继续，从暂停点恢复，不要重开任务。"
            expected_transition = "paused_to_running"
            semantic_obligation = "必须从上一暂停点恢复，不能创建新目标。"
        elif index % 5 == 3:
            kind = "append"
            message = f"第 {index} 轮补充：把补充意见纳入后续执行上下文，记录为可审计证据。"
            expected_transition = "running_with_new_steer"
            semantic_obligation = "补充意见必须进入后续执行上下文并被消费。"
        elif index % 5 == 4:
            kind = "overturn"
            message = f"第 {index} 轮推翻：取消上一轮局部优先级，改以系统级稳定性为最高标准。"
            expected_transition = "running_with_contract_revision"
            semantic_obligation = "必须裁决目标修订，并用新方向覆盖旧局部优先级。"
        else:
            kind = "status"
            message = f"第 {index} 轮状态询问：只报告进度，不改变目标。"
            expected_transition = "running_status_only"
            semantic_obligation = "只能报告状态，不能改变目标或完成标准。"
        turns.append(
            {
                "round": str(index),
                "kind": kind,
                "message": message,
                "expected_transition": expected_transition,
                "semantic_obligation": semantic_obligation,
            }
        )
    return turns


def _loop_control_contract(rounds: int) -> dict[str, Any]:
    turns = _scenario(rounds)
    return {
        "authority": "system_eval.twenty_round_loop_control_contract",
        "contract_id": "contract.twenty_round_loop_control.v1",
        "round_count": rounds,
        "state_model": {
            "initial_state": "running",
            "allowed_states": ["running", "paused", "running_with_pending_steer", "running_with_active_revision", "completed"],
            "terminal_state": "completed",
        },
        "round_contracts": [
            {
                "round": int(item["round"]),
                "kind": item["kind"],
                "expected_transition": item["expected_transition"],
                "semantic_obligation": item["semantic_obligation"],
                "monitor_assertions": _round_monitor_assertions(item),
            }
            for item in turns
        ],
        "aggregate_requirements": {
            "pause_count": 4,
            "resume_count": 4,
            "append_count": 4,
            "overturn_count": 4,
            "status_count": 4,
            "all_rounds_ordered": True,
            "no_duplicate_rounds": True,
            "resume_requires_prior_pause": True,
            "append_requires_later_consumption": True,
            "overturn_requires_revision_decision": True,
            "status_must_not_mutate_goal": True,
            "final_completion_requires_no_pending_control": True,
        },
        "failure_policy": {
            "missing_round": "fail",
            "duplicate_round": "fail",
            "unconsumed_append": "fail",
            "undecided_overturn": "fail",
            "completion_with_pending_control": "fail",
        },
    }


def _round_monitor_assertions(turn: dict[str, str]) -> list[str]:
    kind = turn["kind"]
    if kind == "pause":
        return ["pause_recorded", "goal_preserved"]
    if kind == "resume":
        return ["resume_recorded", "same_task_continued"]
    if kind == "append":
        return ["steer_recorded", "steer_included", "steer_consumed"]
    if kind == "overturn":
        return ["revision_recorded", "revision_decided", "new_priority_applied"]
    return ["status_reported", "goal_not_mutated"]


def _contracts(rounds: int) -> dict[str, Any]:
    loop_contract = _loop_control_contract(rounds)
    return {
        "loop_control": loop_contract,
        "main_node": {
            "authority": "system_eval.semantic_main_node_contract",
            "role": "long_task_semantic_executor",
            "responsibilities": [
                "逐轮处理输入中的语义控制要求",
                "保持同一长任务目标，不因暂停、状态询问或补充意见重开任务",
                "对推翻方向给出裁决并以最新裁决覆盖旧局部优先级",
                "交付结构化证据包给监测节点",
            ],
            "input_contract": {
                "required_fields": ["scenario", "turns"],
                "turn_count": rounds,
                "allowed_turn_kinds": ["pause", "resume", "append", "overturn", "status"],
                "loop_control_contract_id": loop_contract["contract_id"],
            },
            "output_contract": {
                "artifact": "semantic_evidence_packet",
                "required_fields": [
                    "authority",
                    "loop_control_contract_id",
                    "round_count",
                    "turns",
                    "round_results",
                    "semantic_controls",
                    "completion_gate",
                    "claims",
                ],
                "semantic_controls_required": {
                    "pause_count": 4,
                    "resume_count": 4,
                    "append_count": 4,
                    "overturn_count": 4,
                    "status_count": 4,
                },
                "completion_gate_required": {
                    "pending_steer_count_at_finish": 0,
                    "pending_revision_count_at_finish": 0,
                    "premature_completion_rejected": True,
                },
            },
            "forbidden_behavior": [
                "不得替监测节点给出最终裁决",
                "不得省略失败或待处理控制状态",
                "不得把未处理的补充意见标记为已完成",
            ],
        },
        "monitor_node": {
            "authority": "system_eval.semantic_monitor_node_contract",
            "role": "semantic_evidence_auditor",
            "responsibilities": [
                "只审查上游证据包",
                "按边契约和主节点输出契约逐项裁决",
                "发现缺口时输出 missing，不得替主节点补证据",
            ],
            "input_contract": {
                "required_inbound_edge": "edge.main.monitor",
                "required_payload": "semantic_evidence_packet",
                "loop_control_contract_id": loop_contract["contract_id"],
            },
            "output_contract": {
                "artifact": "semantic_monitor_verdict",
                "required_fields": ["authority", "passed", "missing", "checked", "reason"],
                "pass_condition": "missing 为空且所有 required checks 均满足",
            },
            "forbidden_behavior": [
                "不得使用自己生成的证据替代上游证据",
                "不得忽略边契约字段缺失",
            ],
        },
        "edge": {
            "authority": "system_eval.semantic_monitor_edge_contract",
            "edge_id": "edge.main.monitor",
            "source_node_id": "main",
            "target_node_id": "monitor",
            "payload_contract_id": "contract.semantic_evidence_packet.v1",
            "loop_control_contract_id": loop_contract["contract_id"],
            "required_payload_fields": [
                "loop_control_contract_id",
                "round_count",
                "turns",
                "round_results",
                "semantic_controls",
                "completion_gate",
                "claims",
            ],
            "delivery_policy": "summary_and_refs",
            "monitor_must_reject_if_missing": True,
        },
    }


class DualNodeSemanticMonitorModelRuntime:
    def __init__(self, *, rounds: int, round_delay_seconds: float = 0.0) -> None:
        self.rounds = rounds
        self.round_delay_seconds = max(0.0, float(round_delay_seconds or 0.0))
        self.calls: list[dict[str, Any]] = []

    async def invoke_messages(self, messages: Any, **kwargs: Any) -> Any:
        accounting = dict(kwargs.get("accounting_context") or {})
        source = str(accounting.get("source") or "")
        message_text = json.dumps(messages, ensure_ascii=False, default=str)
        self.calls.append({"source": source, "message_text": message_text[:12000]})
        if source != "harness.loop.task_executor.model_action" and "task_execution" not in message_text:
            return SimpleNamespace(content=json.dumps(_action("非节点调用已忽略。"), ensure_ascii=False))
        if "语义监测员" in message_text or '"node_id": "monitor"' in message_text:
            return SimpleNamespace(content=json.dumps(self._monitor_action(message_text), ensure_ascii=False))
        return SimpleNamespace(content=json.dumps(await self._main_action(message_text), ensure_ascii=False))

    async def _main_action(self, message_text: str) -> dict[str, Any]:
        turns = _scenario(self.rounds)
        contracts = _contracts(self.rounds)
        round_results = []
        for item in turns:
            started_at = time.time()
            if self.round_delay_seconds > 0:
                await asyncio.sleep(self.round_delay_seconds)
            finished_at = time.time()
            round_results.append(
                {
                    "round": int(item["round"]),
                    "kind": item["kind"],
                    "expected_transition": item["expected_transition"],
                    "actual_transition": item["expected_transition"],
                    "semantic_obligation": item["semantic_obligation"],
                    "monitor_assertions_satisfied": _round_monitor_assertions(item),
                    "status": "satisfied",
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "elapsed_seconds": round(finished_at - started_at, 3),
                }
            )
        evidence = {
            "authority": "system_eval.dual_node_semantic_evidence",
            "contract_id": "contract.semantic_evidence_packet.v1",
            "loop_control_contract_id": contracts["loop_control"]["contract_id"],
            "round_count": len(turns),
            "turns": turns,
            "round_results": round_results,
            "semantic_controls": {
                "pause_count": sum(1 for item in turns if item["kind"] == "pause"),
                "resume_count": sum(1 for item in turns if item["kind"] == "resume"),
                "append_count": sum(1 for item in turns if item["kind"] == "append"),
                "overturn_count": sum(1 for item in turns if item["kind"] == "overturn"),
                "status_count": sum(1 for item in turns if item["kind"] == "status"),
            },
            "completion_gate": {
                "pending_steer_count_at_finish": 0,
                "pending_revision_count_at_finish": 0,
                "premature_completion_rejected": True,
                "final_direction": "系统级稳定性优先",
            },
            "claims": [
                "20轮语义输入全部被枚举",
                "暂停和恢复成对出现",
                "补充意见进入后续上下文",
                "推翻方向已被裁决并覆盖旧优先级",
                "完成时不存在 pending steer 或 pending revision",
            ],
            "contract_satisfaction": {
                "loop_control_contract": contracts["loop_control"]["authority"],
                "main_node_contract": contracts["main_node"]["authority"],
                "edge_contract": contracts["edge"]["authority"],
                "required_payload_fields_present": True,
            },
            "timing": {
                "round_delay_seconds": self.round_delay_seconds,
                "measured_round_elapsed_seconds": [item["elapsed_seconds"] for item in round_results],
                "total_measured_round_elapsed_seconds": round(sum(float(item["elapsed_seconds"]) for item in round_results), 3),
            },
        }
        return _action(
            "主节点执行证据:\n```json\n" + json.dumps(evidence, ensure_ascii=False, indent=2) + "\n```",
            diagnostics={"semantic_evidence": evidence, "input_seen": "20轮语义压力" in message_text},
        )

    def _monitor_action(self, message_text: str) -> dict[str, Any]:
        contracts = _contracts(self.rounds)
        required_checks = [
            {"field": "contract_id", "tokens": ["contract_id", "contract.semantic_evidence_packet.v1"]},
            {"field": "loop_control_contract_id", "tokens": ["loop_control_contract_id", "contract.twenty_round_loop_control.v1"]},
            {"field": "round_count", "tokens": ["round_count", "20"]},
            {"field": "round_results", "tokens": ["round_results"]},
            {"field": "pause_count", "tokens": ["pause_count", "4"]},
            {"field": "resume_count", "tokens": ["resume_count", "4"]},
            {"field": "append_count", "tokens": ["append_count", "4"]},
            {"field": "overturn_count", "tokens": ["overturn_count", "4"]},
            {"field": "status_count", "tokens": ["status_count", "4"]},
            {"field": "premature_completion_rejected", "tokens": ["premature_completion_rejected", "true"]},
            {"field": "final_direction", "tokens": ["final_direction", "系统级稳定性优先"]},
            {"field": "loop_control_contract", "tokens": ["loop_control_contract", contracts["loop_control"]["authority"]]},
            {"field": "edge_contract", "tokens": ["edge_contract", contracts["edge"]["authority"]]},
        ]
        normalized_text = message_text.replace("\\", "")
        missing = [
            item["field"]
            for item in required_checks
            if not all(str(token) in normalized_text for token in list(item["tokens"]))
        ]
        verdict = {
            "authority": "system_eval.dual_node_semantic_monitor_verdict",
            "contract_id": "contract.semantic_monitor_verdict.v1",
            "passed": not missing,
            "missing": missing,
            "checked": required_checks,
            "contracts": {"monitor_node": contracts["monitor_node"], "edge": contracts["edge"]},
            "reason": "主节点证据包满足20轮语义控制、完成门禁和方向推翻要求。" if not missing else "主节点证据包缺少必要语义证据。",
        }
        return _action(
            "监测节点裁决:\n```json\n" + json.dumps(verdict, ensure_ascii=False, indent=2) + "\n```",
            diagnostics={"monitor_verdict": verdict},
        )


def _build_graph(runtime: Any) -> Any:
    registry = TaskFlowRegistry(runtime.base_dir)
    contracts = _contracts(20)
    graph = registry.upsert_task_graph(
        graph_id=f"graph.system_eval.dual_node_semantic_monitor.{uuid.uuid4().hex[:8]}",
        title="Dual Node Semantic Monitor Experiment",
        graph_kind="multi_agent",
        entry_node_id="main",
        output_node_id="monitor",
        nodes=(
            {
                "node_id": "main",
                "node_type": "agent",
                "title": "主执行节点",
                "task_id": "task.system_eval.semantic_main",
                "agent_id": "agent:0",
                "metadata": {
                    "prompt_contract": {
                        "role_prompt": "你是一名长任务主执行 agent。",
                        "task_instruction": "你需要处理输入中的20轮语义压力要求，输出完整、可审计的执行证据包。",
                        "output_instruction": "只输出证据包，不要替监测节点做裁决。",
                        "definition_of_done": ["20轮输入全部列出", "暂停、恢复、补充、推翻、状态询问都有证据", "完成时无待处理控制状态"],
                    },
                    "semantic_contract": contracts["main_node"],
                },
                "contract_bindings": {"execution": contracts["main_node"], "schema": contracts["main_node"]["output_contract"]},
            },
            {
                "node_id": "monitor",
                "node_type": "agent",
                "title": "语义监测节点",
                "task_id": "task.system_eval.semantic_monitor",
                "agent_id": "agent:0",
                "metadata": {
                    "prompt_contract": {
                        "role_prompt": "你是一名语义监测员。",
                        "task_instruction": "你只审查上游主执行节点交付的证据包是否满足20轮语义压力实验要求。",
                        "output_instruction": "输出 passed、missing、reason。禁止补写主节点没有交付的证据。",
                        "definition_of_done": ["检查20轮数量", "检查暂停恢复", "检查补充吸收", "检查推翻裁决", "检查完成门禁"],
                    },
                    "semantic_contract": contracts["monitor_node"],
                },
                "contract_bindings": {"execution": contracts["monitor_node"], "schema": contracts["monitor_node"]["output_contract"]},
            },
        ),
        edges=(
            {
                "edge_id": "edge.main.monitor",
                "source_node_id": "main",
                "target_node_id": "monitor",
                "edge_type": "handoff",
                "result_delivery_policy": "contract_payload_and_refs",
                "context_filter_policy": {"include_output_keys": ["semantic_evidence"], "max_chars": 50000},
                "payload_contract_id": contracts["edge"]["payload_contract_id"],
                "contract_bindings": {
                    "handoff": contracts["edge"],
                    "schema": {
                        "payload_contract_id": contracts["edge"]["payload_contract_id"],
                        "required_payload_fields": contracts["edge"]["required_payload_fields"],
                        "loop_control_contract_id": contracts["edge"]["loop_control_contract_id"],
                    },
                },
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    return publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)


def _node_task_runs(host: Any, graph_run_id: str) -> list[dict[str, Any]]:
    runs = []
    for item in host.state_index.list_task_runs():
        diagnostics = dict(getattr(item, "diagnostics", {}) or {})
        if diagnostics.get("graph_run_id") == graph_run_id and diagnostics.get("graph_node_id"):
            runs.append({**item.to_dict(), "graph_node_id": str(diagnostics.get("graph_node_id") or "")})
    return sorted(runs, key=lambda item: str(item.get("graph_node_id") or ""))


def _trace(host: Any, task_run_id: str) -> dict[str, Any]:
    return host.get_trace(task_run_id, include_payloads=True, include_model_messages=True) or {}


def _assert_report(report: dict[str, Any]) -> None:
    if report["runner"]["status"] != "completed":
        raise AssertionError(f"graph did not complete: {report['runner']}")
    node_runs = report["node_task_runs"]
    if [item.get("graph_node_id") for item in node_runs] != ["main", "monitor"]:
        raise AssertionError(f"expected main and monitor node task runs: {node_runs}")
    monitor_answer = json.dumps(report["monitor_trace"], ensure_ascii=False)
    if '"passed": true' not in monitor_answer:
        raise AssertionError("monitor node did not pass the main-node evidence")
    main_answer = json.dumps(report["main_trace"], ensure_ascii=False)
    for required in (
        "\"contract_id\": \"contract.semantic_evidence_packet.v1\"",
        "\"loop_control_contract_id\": \"contract.twenty_round_loop_control.v1\"",
        "\"round_count\": 20",
        "\"round_results\"",
        "\"pause_count\": 4",
        "\"resume_count\": 4",
        "\"append_count\": 4",
        "\"overturn_count\": 4",
        "\"status_count\": 4",
        "system_eval.twenty_round_loop_control_contract",
        "system_eval.semantic_monitor_edge_contract",
    ):
        if required not in main_answer:
            raise AssertionError(f"main node evidence missing {required}")
    graph_config = report["graph_config"]
    edge = dict(list(graph_config.get("edges") or [])[0])
    if edge.get("payload_contract_id") != "contract.semantic_evidence_packet.v1":
        raise AssertionError(f"edge contract missing payload_contract_id: {edge}")
    schema = dict(dict(edge.get("contract_bindings") or {}).get("schema") or {})
    if schema.get("loop_control_contract_id") != "contract.twenty_round_loop_control.v1":
        raise AssertionError(f"edge contract missing loop_control_contract_id: {edge}")
    for node_id, contract_authority in {"main": "system_eval.semantic_main_node_contract", "monitor": "system_eval.semantic_monitor_node_contract"}.items():
        node = next((dict(item) for item in list(graph_config.get("nodes") or []) if str(dict(item).get("node_id") or "") == node_id), {})
        execution_contract = dict(dict(dict(node.get("contracts") or {}).get("contract_bindings") or {}).get("execution") or {})
        if str(execution_contract.get("authority") or "") != contract_authority:
            raise AssertionError(f"{node_id} node contract missing authority: {node}")
        prompt = dict(node.get("prompt") or {})
        if node_id == "monitor" and "语义监测员" not in str(prompt.get("role_prompt") or ""):
            raise AssertionError(f"monitor prompt contract was not published: {node}")


async def _run(output_root: Path, *, rounds: int, round_delay_seconds: float = 0.0) -> dict[str, Any]:
    run_id = f"dual-node-semantic-monitor-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = time.time()
    model = DualNodeSemanticMonitorModelRuntime(rounds=rounds, round_delay_seconds=round_delay_seconds)
    runtime = build_query_runtime(model_runtime=model)
    graph_config = _build_graph(runtime)
    start = runtime.graph_harness.start_run(
        session_id=f"session-dual-node-semantic-{uuid.uuid4().hex[:8]}",
        task_id="task.system_eval.dual_node_semantic_monitor",
        graph_config=graph_config,
        initial_inputs={"scenario": "20轮语义压力", "turns": _scenario(rounds)},
    )
    runner = await runtime.graph_harness.run_until_idle(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
        max_node_executions=4,
        max_node_steps=4,
        max_loop_iterations=8,
    )
    finished_at = time.time()
    host = runtime.single_agent_runtime_host
    node_runs = _node_task_runs(host, start.graph_run.graph_run_id)
    traces = {str(item.get("graph_node_id") or ""): _trace(host, str(item["task_run_id"])) for item in node_runs}
    report = {
        "experiment": "dual_node_semantic_monitor",
        "run_id": run_id,
        "output_dir": str(output_dir),
        "rounds": rounds,
        "round_delay_seconds": round_delay_seconds,
        "elapsed_seconds": round(finished_at - started_at, 3),
        "graph_run_id": start.graph_run.graph_run_id,
        "root_task_run_id": start.task_run.task_run_id,
        "contracts": _contracts(rounds),
        "graph_config": graph_config.to_dict(),
        "runner": runner.to_dict(),
        "graph_monitor": runtime.graph_harness.get_graph_run_monitor(start.graph_run.graph_run_id, graph_config=graph_config),
        "node_task_runs": node_runs,
        "main_trace": traces.get("main", {}),
        "monitor_trace": traces.get("monitor", {}),
        "model_calls": model.calls,
    }
    try:
        _assert_report(report)
    except Exception:
        _write_json(output_dir / "debug_report.json", report)
        raise
    _write_json(output_dir / "run_result.json", report)
    _write_markdown_report(output_dir / "report.md", report)
    return report


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Dual Node Semantic Monitor Experiment",
        "",
        f"- run_id: `{report['run_id']}`",
        f"- graph_run_id: `{report['graph_run_id']}`",
        f"- rounds: `{report['rounds']}`",
        f"- passed: `True`",
        f"- node_task_runs: `{len(report['node_task_runs'])}`",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default=str(PROJECT_ROOT / "output" / "test_runs"))
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--round-delay-seconds", type=float, default=0.0)
    args = parser.parse_args()
    try:
        report = asyncio.run(
            _run(
                Path(args.output_root),
                rounds=max(20, int(args.rounds)),
                round_delay_seconds=max(0.0, float(args.round_delay_seconds or 0.0)),
            )
        )
    except Exception as exc:
        print(f"EXPERIMENT FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"passed": True, "run_result": report["output_dir"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
