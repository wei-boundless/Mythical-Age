from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any


class RuntimeBaseDirStub:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)


class MemoryApiRuntimeStub(RuntimeBaseDirStub):
    def __init__(self, base_dir: Path) -> None:
        from memory_system import MemoryFacade

        super().__init__(base_dir)
        self.memory_facade = MemoryFacade(base_dir)
        self.refreshed_paths: list[str] = []

    def refresh_indexes_for_path(self, path: str) -> None:
        self.refreshed_paths.append(path)


class QueryRuntimeMemoryFacadeStub:
    session_memory = SimpleNamespace(
        manager=lambda _session_id: SimpleNamespace(load_state=lambda: None),
        update_runtime_state_from_context_state=lambda *_args, **_kwargs: None,
    )

    def build_memory_context_package(self, *_args, **_kwargs):
        return None

    def build_memory_runtime_view(self, *_args, **_kwargs):
        return {"view_id": "memview:test", "state_snapshot": {}}

    def enqueue_memory_maintenance_after_commit(self, *_args, **_kwargs):
        return SimpleNamespace(
            to_dict=lambda: {
                "attempted": False,
                "queued": True,
                "status": "queued",
                "session_memory_succeeded": False,
                "durable_memory_succeeded": False,
                "durable_write_count": 0,
            }
        )


class EmptySkillRegistryStub:
    skills = []


class PrimarySettingsStub:
    def get_rag_mode(self) -> bool:
        return False

    def get_orchestration_plan_mode(self) -> str:
        return "primary"


class DefaultPermissionStub:
    def current_mode(self) -> str:
        return "default"

    def supported_modes(self) -> list[str]:
        return ["default"]


class InMemorySessionManagerStub:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def load_session_record(self, _session_id):
        return {"messages": list(self.messages)}

    def load_session_for_agent(self, _session_id, *, include_compressed_context: bool = False):
        return list(self.messages)

    def load_session(self, _session_id):
        return list(self.messages)

    def append_messages(self, _session_id, messages):
        self.messages.extend(messages)
        return list(messages)


class EmptyToolRuntimeStub:
    registry = None
    definitions = []
    instances = []

    def get_definition(self, _name):
        return None

    def get_instance(self, _name):
        return None


class SingleMessageModelRuntimeStub:
    def __init__(self, content: str = "单轮收口回答") -> None:
        self.content = content

    async def invoke_messages(self, _messages, **_kwargs):
        return SimpleNamespace(content=self.content)


class StreamingMessageModelRuntimeStub(SingleMessageModelRuntimeStub):
    def __init__(self, *, chunks: list[str], content: str | None = None) -> None:
        super().__init__(content=content or "".join(chunks))
        self.chunks = list(chunks)

    async def astream_messages(self, _messages, **_kwargs):
        for chunk in self.chunks:
            yield SimpleNamespace(content=chunk)


def isolated_backend_root(prefix: str = "backend-test-") -> Path:
    root = Path(tempfile.mkdtemp(prefix=prefix)) / "backend"
    root.mkdir(parents=True, exist_ok=True)
    return root


def build_query_runtime(
    *,
    base_dir: Path | None = None,
    settings_service: Any | None = None,
    session_manager: Any | None = None,
    memory_facade: Any | None = None,
    retrieval_service: Any | None = None,
    tool_runtime: Any | None = None,
    skill_registry: Any | None = None,
    permission_service: Any | None = None,
    model_runtime: Any | None = None,
):
    from query import QueryRuntime

    return QueryRuntime(
        base_dir=base_dir or isolated_backend_root(),
        settings_service=settings_service or PrimarySettingsStub(),
        session_manager=session_manager or InMemorySessionManagerStub(),
        memory_facade=memory_facade or QueryRuntimeMemoryFacadeStub(),
        retrieval_service=retrieval_service or SimpleNamespace(),
        tool_runtime=tool_runtime or EmptyToolRuntimeStub(),
        skill_registry=skill_registry or EmptySkillRegistryStub(),
        permission_service=permission_service or DefaultPermissionStub(),
        model_runtime=model_runtime or SingleMessageModelRuntimeStub(),
    )
