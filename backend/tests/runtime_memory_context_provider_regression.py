from __future__ import annotations

import asyncio
from types import SimpleNamespace

from memory_system.runtime_context_provider import RuntimeMemoryContextProvider


class _Payload:
    def __init__(self, payload):
        self._payload = payload

    def to_dict(self):
        return dict(self._payload)


class _CapturingBundleService:
    def __init__(self) -> None:
        self.profiles: list[dict] = []

    async def abuild_memory_runtime_view(self, **kwargs):
        profile = dict(kwargs.get("memory_request_profile") or {})
        self.profiles.append(profile)
        return _Payload(
            {
                "view_id": "view:test",
                "diagnostics": {
                    "read_plan": {
                        "requested_memory_layers": list(profile.get("requested_memory_layers") or []),
                    }
                },
            }
        )

    async def abuild_memory_context_package_result(self, **_kwargs):
        return _Payload({"package": {"model_visible_sections": {}}})


def _provider(bundle: _CapturingBundleService) -> RuntimeMemoryContextProvider:
    return RuntimeMemoryContextProvider(
        bundle_service_getter=lambda: bundle,
        session_record_loader=lambda _session_id: {},
        recent_messages_loader=lambda _session_id: [],
    )


def test_generic_task_continuation_does_not_open_long_term_memory() -> None:
    bundle = _CapturingBundleService()
    profile = SimpleNamespace(agent_profile_id="main_interactive_agent", allowed_memory_scopes=("long_term_candidate",))

    asyncio.run(
        _provider(bundle).for_turn(
            session_id="session-runtime-memory-generic",
            turn_id="turn:1",
            user_message="继续检查 prompt cache",
            session_context={},
            agent_runtime_profile=profile,
            runtime_assembly={},
            environment_binding={},
            active_work_context=None,
            recent_work_outcome=None,
        )
    )

    assert bundle.profiles[-1]["requested_memory_layers"] == ["state"]
    assert bundle.profiles[-1]["allow_long_term_memory"] is False


def test_explicit_memory_read_opens_long_term_memory() -> None:
    bundle = _CapturingBundleService()
    profile = SimpleNamespace(agent_profile_id="main_interactive_agent", allowed_memory_scopes=("long_term_candidate",))

    asyncio.run(
        _provider(bundle).for_turn(
            session_id="session-runtime-memory-explicit",
            turn_id="turn:1",
            user_message="上次关于记忆系统的约定是什么？",
            session_context={},
            agent_runtime_profile=profile,
            runtime_assembly={},
            environment_binding={},
            active_work_context=None,
            recent_work_outcome=None,
        )
    )

    assert bundle.profiles[-1]["requested_memory_layers"] == ["state", "long_term"]
    assert bundle.profiles[-1]["allow_long_term_memory"] is True


def test_environment_binding_alone_does_not_open_long_term_memory() -> None:
    bundle = _CapturingBundleService()
    profile = SimpleNamespace(agent_profile_id="main_interactive_agent", allowed_memory_scopes=("long_term_candidate",))

    asyncio.run(
        _provider(bundle).for_turn(
            session_id="session-runtime-memory-environment-only",
            turn_id="turn:1",
            user_message="检查当前文件。",
            session_context={},
            agent_runtime_profile=profile,
            runtime_assembly={},
            environment_binding={
                "task_environment_id": "env.coding.vibe_workspace",
                "environment_id": "env.coding.vibe_workspace",
                "binding_kind": "conversation_active_task_environment",
            },
            active_work_context=None,
            recent_work_outcome=None,
        )
    )

    assert bundle.profiles[-1]["requested_memory_layers"] == ["state"]
    assert bundle.profiles[-1]["allow_long_term_memory"] is False
    assert bundle.profiles[-1]["task_environment_id"] == "env.coding.vibe_workspace"


def test_task_execution_rejects_non_runtime_memory_profile_layers_before_bundle_call() -> None:
    for layer in ("task_durable", "artifact_refs"):
        bundle = _CapturingBundleService()
        error = ""

        try:
            asyncio.run(
                _provider(bundle).for_task_execution(
                    {
                        "session_id": "session-runtime-memory-invalid",
                        "task_run": {"task_run_id": "taskrun:invalid", "task_id": "task.invalid"},
                        "contract": {
                            "memory_request_profile": {
                                "requested_memory_layers": ["state", layer],
                                "allow_long_term_memory": True,
                            }
                        },
                        "agent_runtime_profile": SimpleNamespace(allowed_memory_scopes=()),
                    }
                )
            )
        except ValueError as exc:
            error = str(exc)

        assert "memory layer" in error.lower()
        assert bundle.profiles == []
