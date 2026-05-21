from __future__ import annotations

from pathlib import Path

from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile
from runtime.contracts.compiler import compile_workflow_contract_manifest
from task_system import TaskContractRegistry, TaskFlowRegistry, TaskWorkflowRegistry


def _seed_basic_contracts(registry: TaskContractRegistry) -> None:
    registry.upsert_contract_spec(
        {
            "contract_id": "contract.test.user_goal",
            "title_zh": "测试用户目标",
            "contract_kind": "global_task",
            "input_fields": [
                {
                    "field_id": "goal",
                    "title_zh": "目标",
                    "field_type": "string",
                    "required": True,
                    "source_hint": "user_input",
                    "visibility": "model_visible",
                }
            ],
        }
    )
    registry.upsert_contract_spec(
        {
            "contract_id": "contract.test.markdown_result",
            "title_zh": "测试 Markdown 结果",
            "contract_kind": "final_output",
            "output_fields": [
                {
                    "field_id": "answer_markdown",
                    "title_zh": "回答正文",
                    "field_type": "string",
                    "required": True,
                    "source_hint": "upstream_output",
                    "visibility": "model_visible",
                }
            ],
            "acceptance_rules": [
                {
                    "rule_id": "answer_present",
                    "title_zh": "回答存在",
                    "rule_type": "required_field_present",
                    "severity": "error",
                    "target_field": "answer_markdown",
                }
            ],
        }
    )


def test_workflow_contract_compiler_builds_valid_manifest(tmp_path: Path) -> None:
    contract_registry = TaskContractRegistry(tmp_path)
    _seed_basic_contracts(contract_registry)
    flow_registry = TaskFlowRegistry(tmp_path)
    workflow_registry = TaskWorkflowRegistry(tmp_path)

    workflow = workflow_registry.upsert_workflow(
        workflow_id="workflow.test.contract_manifest",
        title="契约编译测试工作流",
        steps=(
            {"step_id": "understand", "title": "理解目标"},
            {"step_id": "finalize", "title": "形成结果", "contract_id": "contract.test.markdown_result"},
        ),
        output_contract_id="contract.test.markdown_result",
    )
    task = flow_registry.upsert_specific_task_record(
        task_id="task.test.contract_manifest",
        task_title="契约编译测试任务",
        task_family="test",
        input_contract_id="contract.test.user_goal",
        output_contract_id="contract.test.markdown_result",
        default_workflow_id=workflow.workflow_id,
    )
    profile = AgentRuntimeProfile(
        agent_profile_id="contract_test_profile",
        agent_id="agent:test",
        allowed_runtime_lanes=("readonly_exploration",),
    )

    manifest = compile_workflow_contract_manifest(
        contract_registry=contract_registry,
        task=task,
        workflow=workflow,
        agent_profile=profile,
        agent_id="agent:test",
        runtime_lane="readonly_exploration",
    )

    assert manifest.valid is True
    assert manifest.manifest_kind == "workflow"
    assert manifest.workflow_id == "workflow.test.contract_manifest"
    assert {item.contract_id for item in manifest.global_contracts} == {
        "contract.test.user_goal",
        "contract.test.markdown_result",
    }
    assert [item.node_id for item in manifest.node_contracts] == ["understand", "finalize"]
    assert manifest.acceptance_contracts[0].rule_count >= 0


def test_workflow_contract_compiler_reports_missing_contract_and_runtime_mismatch(tmp_path: Path) -> None:
    contract_registry = TaskContractRegistry(tmp_path)
    _seed_basic_contracts(contract_registry)
    flow_registry = TaskFlowRegistry(tmp_path)
    workflow_registry = TaskWorkflowRegistry(tmp_path)

    workflow = workflow_registry.upsert_workflow(
        workflow_id="workflow.test.invalid_contract_manifest",
        title="契约编译失败工作流",
        steps=({"step_id": "finalize", "title": "形成结果"},),
        output_contract_id="contract.test.missing_output",
    )
    task = flow_registry.upsert_specific_task_record(
        task_id="task.test.invalid_contract_manifest",
        task_title="契约编译失败任务",
        task_family="test",
        input_contract_id="contract.test.user_goal",
        output_contract_id="contract.test.missing_output",
        default_workflow_id=workflow.workflow_id,
    )
    profile = AgentRuntimeProfile(
        agent_profile_id="contract_test_profile",
        agent_id="agent:test",
        allowed_runtime_lanes=("readonly_exploration",),
    )

    manifest = compile_workflow_contract_manifest(
        contract_registry=contract_registry,
        task=task,
        workflow=workflow,
        agent_profile=profile,
        agent_id="agent:test",
        runtime_lane="test_lane",
    )

    issue_codes = {item.code for item in manifest.issues}
    assert manifest.valid is False
    assert "contract_spec_missing" in issue_codes
    assert "runtime_lane_unknown" in issue_codes
    assert "runtime_lane_not_allowed" in issue_codes
