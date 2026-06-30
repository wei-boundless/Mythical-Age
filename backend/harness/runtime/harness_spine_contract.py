from __future__ import annotations

from typing import Any


HARNESS_SPINE_CONTRACT_AUTHORITY = "harness.runtime.harness_spine_contract"
TASK_EXECUTOR_RUNNER_CONTRACT_ID = "harness_spine.task_executor_background_runner"
TASK_EXECUTOR_BASE_ACTION_TYPES = ("respond", "ask_user", "tool_call", "block")
TASK_EXECUTOR_CONDITIONAL_ACTION_TYPES = ("pause_for_user_steer",)
TASK_EXECUTOR_FORBIDDEN_ORDINARY_ACTION_TYPES = (
    "request_task_run",
    "active_work_control",
    "resume_task_recovery",
)


def task_executor_runner_contract(
    *,
    scheduler: str = "",
    task_run_id: str = "",
    turn_id: str = "",
    recovered_from: str = "",
) -> dict[str, Any]:
    return {
        "contract_id": TASK_EXECUTOR_RUNNER_CONTRACT_ID,
        "authority": HARNESS_SPINE_CONTRACT_AUTHORITY,
        "runner_role": "durable_task_background_runner",
        "task_run_semantics": "TaskRun is a durable work resource, not the default conversation spine.",
        "default_model_entrypoint": "harness.loop.single_agent_turn",
        "execution_entrypoint": "harness.loop.task_executor",
        "controller_ref": "harness.loop.task_executor_controller.TaskExecutorController",
        "control_gateway_ref": "harness.runtime.task_run_control_gateway.TaskRunControlGateway",
        "packet_ref": "harness.runtime.compiler.compile_task_execution_packet",
        "action_surface_authority": "harness.runtime.packet_assembler._task_execution_model_action_surface",
        "action_schema_ref": "harness.runtime.compiler.task_execution_action_schema",
        "model_action_authority": "harness.loop.model_action_protocol",
        "admission_authority": "harness.loop.admission",
        "permit_authority": "harness.loop.action_permit",
        "tool_execution_authority": "runtime.tool_runtime.tool_control_plane",
        "output_commit_authority": "harness.runtime.output_commit_authority",
        "base_action_types": list(TASK_EXECUTOR_BASE_ACTION_TYPES),
        "conditional_action_types": list(TASK_EXECUTOR_CONDITIONAL_ACTION_TYPES),
        "forbidden_action_types": list(TASK_EXECUTOR_FORBIDDEN_ORDINARY_ACTION_TYPES),
        "ordinary_turn_policy": "ordinary user turns and conversation continue actions enter single_agent_turn; TaskRun supplies durable state and environment, not a detached model loop.",
        "migration_target": "single_agent_turn + task overlay for ordinary task-bound work",
        "forbidden_routes": [
            "task_executor_must_not_interpret_new_user_input_as_default_turn",
            "task_execution_packet_must_not_open_request_task_run",
            "task_execution_packet_must_not_open_active_work_control",
            "task_execution_packet_must_not_open_resume_task_recovery",
            "conversation_continue_must_not_schedule_task_executor",
            "active_work_control_must_not_resume_task_executor",
            "task_executor_final_text_must_not_bypass_output_commit_authority",
        ],
        "scheduler": str(scheduler or ""),
        "task_run_id": str(task_run_id or ""),
        "turn_id": str(turn_id or ""),
        "recovered_from": str(recovered_from or ""),
    }


def task_executor_runner_contract_inventory() -> tuple[dict[str, Any], ...]:
    return (task_executor_runner_contract(),)
