from __future__ import annotations

from task_system.assembly import TaskRuntimeAssemblyRequestBuilder
from task_system.lifecycle import TaskLifecycleFactory
from task_system.primitives import TaskActivationRequest


def test_runtime_assembly_request_is_built_from_task_lifecycle_only() -> None:
    activation = TaskActivationRequest(
        activation_id="activation:runtime-asm",
        session_id="session:test",
        source="explicit_requirement",
        dispatch="order_dispatch",
        objective="Prepare runtime assembly request.",
        environment_id="env.vibe_coding",
        resource_needs={"memory": {"scope": "conversation"}},
        capability_needs={
            "tools": {"allowed": ["op.read_file"]},
            "agent_assignment": {"default_agent_id": "agent:0"},
        },
        expected_output={
            "contract_id": "contract:test",
            "artifact_scope": {"root": "artifact:test"},
        },
        acceptance_hint={"must_verify": True},
    )
    creation = TaskLifecycleFactory().create_from_activation(activation)
    assert creation.lifecycle is not None

    request = TaskRuntimeAssemblyRequestBuilder().build(creation.lifecycle)
    payload = request.to_dict()

    assert request.task_lifecycle_ref == creation.lifecycle.task_id
    assert request.environment_ref == "env.vibe_coding"
    assert request.activation_ref == activation.activation_id
    assert request.agent_assignment_ref
    assert request.tool_scope_ref
    assert request.output_contract_ref
    assert payload["authority"] == "task_system.task_runtime_assembly_request"
    assert "task_selection" not in str(payload)
    assert "projection_id" not in str(payload)
    assert "domain_id" not in str(payload)
