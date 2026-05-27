from __future__ import annotations

import pytest

from task_system.lifecycle import InMemoryTaskLifecycleStore, TaskLifecycleFactory, TaskLifecycleRegistry
from task_system.primitives import AgentWorkLifecycleIntent, TaskActivationRequest


def test_lifecycle_registry_uses_task_system_store_without_runtime_state_index() -> None:
    store = InMemoryTaskLifecycleStore()
    registry = TaskLifecycleRegistry(store)
    activation = TaskActivationRequest(
        activation_id="activation:test",
        session_id="session:test",
        source="explicit_requirement",
        dispatch="order_dispatch",
        objective="Build the task lifecycle primitive.",
        environment_id="env.vibe_coding",
    )
    creation = TaskLifecycleFactory().create_from_activation(
        activation,
        legacy_refs={"task_order_id": "order:test"},
    )

    assert creation.lifecycle is not None
    assert creation.runtime_assembly_request is not None
    registry.upsert_creation(creation)

    assert registry.get_lifecycle(creation.lifecycle.task_id) == creation.lifecycle
    assert registry.get_lifecycle_by_activation(activation.activation_id) == creation.lifecycle
    assert registry.get_lifecycle_by_order("order:test") == creation.lifecycle
    assert registry.get_runtime_assembly_request(creation.runtime_assembly_request.request_id) == creation.runtime_assembly_request


def test_agent_work_lifecycle_intent_and_explicit_order_enter_same_factory() -> None:
    factory = TaskLifecycleFactory()
    intent = AgentWorkLifecycleIntent(
        intent_id="intent:agent:test",
        parent_task_id="tasklife:parent",
        objective="Run an independent review pass.",
        reason="The review has separate output and acceptance.",
        environment_hint="env.writing",
        expected_output={"deliverable": "review_report"},
        acceptance_hint={"must_decide": True},
        lifecycle_need=("independent_acceptance",),
    )
    agent_activation = TaskActivationRequest(
        activation_id="activation:agent:test",
        session_id="session:test",
        source="agent_derived",
        dispatch="agent_dispatch",
        objective=intent.objective,
        environment_id=intent.environment_hint,
        parent_task_id=intent.parent_task_id,
        source_ref=intent.intent_id,
        expected_output=intent.expected_output,
        acceptance_hint=intent.acceptance_hint,
        lifecycle_need=intent.lifecycle_need,
    )
    explicit_activation = TaskActivationRequest(
        activation_id="activation:explicit:test",
        session_id="session:test",
        source="explicit_requirement",
        dispatch="order_dispatch",
        objective="Run an independent review pass.",
        environment_id="env.writing",
    )

    agent_creation = factory.create_from_activation(agent_activation)
    explicit_creation = factory.create_from_activation(explicit_activation)

    assert agent_creation.lifecycle is not None
    assert explicit_creation.lifecycle is not None
    assert agent_creation.lifecycle.source == "agent_derived"
    assert explicit_creation.lifecycle.source == "explicit_requirement"
    assert agent_creation.lifecycle.environment_id == explicit_creation.lifecycle.environment_id
    assert agent_creation.lifecycle.acceptance_policy == {"must_decide": True}


def test_lifecycle_factory_rejects_unknown_environment_without_domain_fallback() -> None:
    activation = TaskActivationRequest(
        activation_id="activation:bad-env",
        session_id="session:test",
        source="explicit_requirement",
        dispatch="order_dispatch",
        objective="Run with unknown environment.",
        environment_id="domain.development",
    )

    with pytest.raises(ValueError, match="unknown task environment"):
        TaskLifecycleFactory().create_from_activation(activation)
