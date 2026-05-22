from __future__ import annotations

from types import SimpleNamespace

from runtime.contracts.continuation_policy import derive_stage_contracts_from_graph, parse_stage_contracts
from task_system.runtime_semantics.length_budget import compile_length_budget
from task_system.runtime_semantics.quality_gates import (
    count_text_units_for_quality_gate,
    length_budget_quality_gate,
    stage_business_acceptance,
)
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from task_system.graphs.task_graph_models import task_graph_from_dict
from text_metric import count_text_units


def test_length_budget_compiles_from_graph_contract_bindings() -> None:
    graph = task_graph_from_dict(
        {
            "graph_id": "graph.test.length_budget",
            "title": "长度预算测试图",
            "contract_bindings": {
                "runtime": {
                    "length_budget": {
                        "budget_scope": "batch",
                        "measurement_mode": "text_units",
                        "unit_kind": "record",
                        "unit_label_zh": "记录",
                        "batch_unit_count": 10,
                        "target_units": 18000,
                        "min_units": 12000,
                        "max_units": 24000,
                    }
                }
            },
            "nodes": [
                {
                    "node_id": "draft",
                    "title": "处理节点",
                    "node_type": "agent_role",
                    "agent_id": "agent:0",
                }
            ],
        }
    )

    runtime_spec = compile_task_graph_definition_runtime_spec(graph=graph)
    budget = runtime_spec.diagnostics["length_budget"]

    assert budget["configured"] is True
    assert budget["budget_scope"] == "batch"
    assert budget["measurement_mode"] == "text_units"
    assert budget["target_units"] == 18000
    assert runtime_spec.diagnostics["length_budget_preview"]["unit_label_zh"] == "记录"


def test_length_budget_quality_gate_rejects_underfilled_text_units() -> None:
    budget = compile_length_budget(
        explicit={
            "budget_scope": "batch",
            "measurement_mode": "text_units",
            "target_units": 12,
            "min_units": 10,
            "max_units": 20,
        },
        source_ref="draft",
    ).to_dict()

    result = length_budget_quality_gate(
        "第一章 太短",
        explicit_inputs={},
        length_budget=budget,
    )

    assert result["accepted"] is False
    assert any(str(issue).startswith("insufficient_metric:") for issue in result["issues"])


def test_length_budget_quality_gate_accepts_chinese_text_units() -> None:
    budget = compile_length_budget(
        explicit={
            "budget_scope": "batch",
            "measurement_mode": "text_units",
            "target_units": 8,
            "min_units": 6,
            "max_units": 20,
        },
        source_ref="draft",
    ).to_dict()

    result = length_budget_quality_gate(
        "天地初开灵光流转",
        explicit_inputs={},
        length_budget=budget,
    )

    assert result["accepted"] is True
    assert result["content_metric_total"] >= 8


def test_runtime_quality_gate_uses_shared_text_metric_counter() -> None:
    content = "天地玄黄 alpha beta"

    assert count_text_units(content) == 6
    assert count_text_units_for_quality_gate(content) == count_text_units(content)


def test_length_budget_batch_count_alone_is_not_configured() -> None:
    budget = compile_length_budget(
        explicit={
            "budget_scope": "batch",
            "measurement_mode": "text_units",
            "unit_kind": "record",
            "batch_unit_count": 10,
        },
        source_ref="draft",
    ).to_dict()

    assert budget["configured"] is False

    acceptance = stage_business_acceptance(
        stage_id="draft",
        contract={"length_budget": budget},
        explicit_inputs={},
        final_content="短内容",
        output_refs=[],
        terminal_status="completed",
        requires_file_artifact_refs=False,
    )

    assert acceptance["accepted"] is True
    assert acceptance["policy"] == "technical_completion"


def test_length_budget_normalizes_legacy_volume_scope_to_group() -> None:
    budget = compile_length_budget(
        explicit={
            "budget_scope": "volume",
            "target_units": 100,
        },
        source_ref="legacy",
    ).to_dict()

    assert budget["budget_scope"] == "group"
    assert "length_budget_scope_invalid" not in budget["diagnostics"]["issues"]


def test_stage_business_acceptance_rejects_pseudo_tool_output() -> None:
    acceptance = stage_business_acceptance(
        stage_id="outline_design",
        contract={},
        explicit_inputs={},
        final_content="<read_file>\n<path>outline_review.md</path>\n</read_file>",
        output_refs=["artifact:output/outline.md"],
        terminal_status="completed",
        requires_file_artifact_refs=True,
    )

    assert acceptance["accepted"] is False
    assert acceptance["policy"] == "protocol_boundary"
    assert "protocol_boundary:pseudo_tool_output" in acceptance["issues"]


def test_length_budget_tokens_mode_declares_text_units_fallback_until_token_meter_exists() -> None:
    budget = compile_length_budget(
        explicit={
            "measurement_mode": "tokens",
            "target_units": 4,
            "min_units": 4,
        },
        source_ref="draft",
    ).to_dict()

    result = length_budget_quality_gate(
        "天地玄黄",
        explicit_inputs={},
        length_budget=budget,
    )

    assert result["accepted"] is True
    assert result["measurement_mode"] == "tokens"
    assert result["measurement_fallback"] == "text_units_counter_used_for_length_budget_until_token_meter_is_bound"


def test_stage_contract_derives_node_length_budget_from_contract_bindings() -> None:
    coordination_task = SimpleNamespace(
        graph_id="graph.test.node_length_budget",
        graph_nodes=(
            {
                "node_id": "draft",
                "task_id": "task.test.draft",
                "agent_id": "agent:draft",
                "contract_bindings": {
                    "runtime": {
                        "length_budget": {
                            "budget_scope": "node",
                            "measurement_mode": "text_units",
                            "target_units": 1200,
                            "min_units": 1000,
                            "max_units": 1600,
                        }
                    }
                },
            },
        ),
        graph_edges=(),
        metadata={},
        subtask_refs=("task.test.draft",),
    )

    contracts = derive_stage_contracts_from_graph(
        coordination_task=coordination_task,
        topology_nodes=list(coordination_task.graph_nodes),
        topology_edges=[],
    )

    assert len(contracts) == 1
    assert contracts[0].length_budget["configured"] is True
    assert contracts[0].length_budget["budget_scope"] == "node"
    assert contracts[0].length_budget["target_units"] == 1200


def test_parse_stage_contract_inherits_topology_node_contract_binding_length_budget() -> None:
    coordination_task = SimpleNamespace(
        graph_id="graph.test.explicit_stage_node_length_budget",
        graph_nodes=(),
        graph_edges=(),
        metadata={
            "stage_contracts": [
                {
                    "stage_id": "draft",
                    "task_ref": "task.test.draft",
                }
            ]
        },
        subtask_refs=("task.test.draft",),
    )
    topology_nodes = [
        {
            "node_id": "draft",
            "task_id": "task.test.draft",
            "contract_bindings": {
                "runtime": {
                    "length_budget": {
                        "budget_scope": "batch",
                        "target_units": 3000,
                        "min_units": 2400,
                    }
                }
            },
        }
    ]

    contracts = parse_stage_contracts(
        coordination_task=coordination_task,
        topology_nodes=topology_nodes,
        topology_edges=[],
    )

    assert len(contracts) == 1
    assert contracts[0].length_budget["configured"] is True
    assert contracts[0].length_budget["budget_scope"] == "batch"
    assert contracts[0].length_budget["target_units"] == 3000
